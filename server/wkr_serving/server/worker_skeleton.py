#!/usr/bin/env python
# -*- coding: utf-8 -*-
# Han Xiao <artex.xh@gmail.com> <https://hanxiao.github.io>
import multiprocessing
import os
import random
import sys
import threading
import time
from collections import defaultdict
from datetime import datetime
from itertools import chain
from multiprocessing import Process
from multiprocessing.pool import Pool

import numpy as np
import zmq
import zmq.decorators as zmqd
from termcolor import colored
from zmq.utils import jsonapi

from .helper import *
from .protocol import *
from .http import BertHTTPProxy
from .zmq_decor import multi_socket

class WKRWorkerSkeleton(Process):
    def __init__(self, id, args, worker_address_list, sink_address, device_id, gpu_fraction, model_name, batch_size, batch_timeout, tmp_dir, name='WORKER', color='yellow'):
        super().__init__()
        self.name = name
        self.color = color
        self.worker_id = id
        self.device_id = device_id
        self.transfer_proto = args.protocol

        self.daemon = True
        self.exit_flag = multiprocessing.Event()
        self.worker_address = worker_address_list
        self.num_concurrent_socket = len(self.worker_address)
        self.sink_address = sink_address

        self.gpu_memory_fraction = gpu_fraction
        self.model_dir = args.model_dir
        self.verbose = args.verbose

        self.model_name = model_name
        self.tmp_folder = os.path.join(self.model_dir, tmp_dir)
        if not os.path.exists(self.tmp_folder):
            os.makedirs(self.tmp_folder)

        self.batch_size = batch_size
        self.batch_group_timeout = batch_timeout

        # self.use_fp16 = args.fp16
        self.is_ready = multiprocessing.Event()

        self.logdir = args.log_dir
        self.logger = set_logger(colored('%s-%s' % (self.name, str(self.worker_id)), self.color), logger_dir=self.logdir, verbose=self.verbose)

    def close(self):
        self.logger.info('shutting down...')
        self.exit_flag.set()
        self.is_ready.clear()
        self.terminate()
        self.join()
        self.logger.info('terminated!')

    def get_env(self, device_id, tmp_dir):
        return []

    def get_model(self, envs, model_dir, model_name, tmp_dir):
        return []

    def get_preprocess(self, envs):
        def preprocessing(input):
            return input
        return preprocessing

    def get_postprocess(self, envs):
        def post_process(output):
            return output
        return post_process

    def predict(self, model, input):
        return input

    def batching(self, list_input):
        if self.transfer_proto == 'obj':
            return list_input
        else:
            processed = [np.expand_dims(a, axis=0) for a in list_input]
            return np.vstack(processed)
            
    def load_raw_msg(self, sock):
        client, req_id, msg, msg_info = recv_from_prev(self.transfer_proto, sock)
        return client, req_id, msg

    def new_logger(self):
        name = '%s-%s' % (self.name, str(self.worker_id))
        color = self.color
        return LoggerSeperate(name, color, logger_dir=self.logdir, verbose=self.verbose)

    def run(self):
        self._run()

    def process_output(self, data, client, req_id, target_sink):
        send_to_next(self.transfer_proto, client, req_id, data, target_sink)

    @zmqd.socket(zmq.PUSH)
    @multi_socket(zmq.PULL, num_socket='num_concurrent_socket')
    def _run(self, sink_embed, *receivers):
        # Windows does not support logger in MP environment, thus get a new logger
        # inside the process for better compatibility
        logger = self.new_logger()

        logger.info('use device %s, load graph from %s/%s' %
                    ('cpu' if self.device_id < 0 else ('gpu: %d' % self.device_id), self.model_dir, self.model_name))

        envs = self.get_env(self.device_id, self.tmp_folder)
        input_preprocessor = self.get_preprocess(envs)
        output_postprocessor = self.get_postprocess(envs)
        model = self.get_model(envs, self.model_dir, self.model_name, self.tmp_folder)

        for sock, addr in zip(receivers, self.worker_address):
            sock.connect(addr)
        sink_embed.connect(self.sink_address)

        def record_statistic(diction):
            push_dic = {}
            for k, v in diction.items():
                push_dic[str(k)] = float(v)
            send_to_next_raw(to_bytes(''), to_bytes(''), jsonapi.dumps(push_dic), ServerCmd.statistic, sink_embed)

        self.record_statistic = record_statistic

        generator = self.input_fn_builder(receivers, input_preprocessor, sink_embed)
        for msg in generator():
            client_ids, input_data = msg['client_ids'], msg['input_data']
            try:
                start = time.time()
                outputs = self.predict(model, input_data)
                end = time.time()
                predict_time = (end-start)*1000
                predict_time_per_input = predict_time/len(input_data)
                logger.info('predict {} input in {:0.4f}ms, avg/item: {:0.4f}ms'.format(len(input_data), predict_time, predict_time_per_input))

                record_statistic({
                    'sys_batchsize': len(input_data),
                    'sys_predict': predict_time_per_input
                })

                if len(outputs) != len(input_data):
                    raise Exception("Output after process by predict func not match. input: {}, output: {}".format(input_data, outputs))

                outputs = output_postprocessor(outputs)
                for client_id, output in zip(client_ids, outputs):
                    cliend, req_id = client_id.split('#')
                    self.process_output(output, cliend, req_id, sink_embed)
                    logger.info('sent to sink\tjob id: {}#{}'.format(cliend, req_id))
                    
            except Exception as e:
                import traceback
                tb = traceback.format_exc()
                logger.error('{}'.format(e), exc_info=True)

                # building exception message
                cids = list(set([client_id.split('#')[0] for client_id in client_ids]))
                exception_msg = 'Exception when processing input batch of {} elements, from {} different client ids ({}). Please check your input.'.format(len(input_data), len(cids), ', '.join(cids))
                exception_msg = '{}\n{}\n{}'.format(tb, e, exception_msg)
                # send exception for all client in batches
                for client_id in client_ids:
                    cliend, req_id = client_id.split('#')
                    send_to_next_raw(to_bytes(cliend), to_bytes(req_id), to_bytes(exception_msg), ServerCmd.exception, sink_embed)

            # Prepare to shutdown this process
            if self.exit_flag.is_set():
                break

    def input_fn_builder(self, socks, input_preprocessor, sink_embed):
        def gen():
            # Windows does not support logger in MP environment, thus get a new logger
            # inside the process for better compatibility
            logger = self.new_logger()

            poller = zmq.Poller()
            for sock in socks:
                poller.register(sock, zmq.POLLIN)

            self.is_ready.set()
            logger.info('ready and listening!')

            def get_single_data(timeout=20):
                events = dict(poller.poll(timeout=timeout))
                if events:
                    for sock_idx, sock in enumerate(socks):
                        if sock in events:
                            try:
                                client, req_id, msg = self.load_raw_msg(sock)
                                logger.info('new job\tsocket: {}\tclient: {}#{}'.format(sock_idx, client, req_id))
                                return {
                                    'client_id': client+'#'+req_id,
                                    'client_msg': msg
                                }
                            except DecodeObjectException as e:
                                # return error to client
                                client, req_id = e.client, e.req_id
                                exception_msg = '''
                                {}
                                \n
                                Error while decoding input from client: {}#{}
                                '''.format(e, to_str(client), to_str(req_id))
                                send_to_next_raw(to_bytes(client), to_bytes(req_id), to_bytes(exception_msg), ServerCmd.exception, sink_embed)
                                raise e
                            except Exception as e:
                                raise e
                return None

            while not self.exit_flag.is_set():
                try:
                    datas = []
                    for _ in range(self.batch_size):
                        d = get_single_data(timeout=self.batch_group_timeout)
                        if d is not None:
                            datas.append(d)
                    if len(datas) > 0:
                        client_ids = [d['client_id'] for d in datas]
                        batch_raw = [d['client_msg'] for d in datas]
                        batch = self.batching(batch_raw)
                        batch_processed = input_preprocessor(batch)
                        yield {
                            'client_ids': client_ids,
                            'input_data': batch_processed
                        }
                except Exception as e:
                    import traceback
                    tb=traceback.format_exc()
                    logger.error('{}\n{}'.format(e, tb))
                    # TODO: handler crash report here

        return gen