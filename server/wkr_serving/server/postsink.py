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

from .statistic import ServerStatistic

class WKRSink(Process):
    def __init__(self, args, nav_to_sink_addr, worker_socket_addrs):
        super().__init__()
        self.port = args.port_out
        self.exit_flag = multiprocessing.Event()
        self.nav_to_sink_addr = nav_to_sink_addr
        self.verbose = args.verbose
        self.is_ready = multiprocessing.Event()
        self.worker_socket_addrs = worker_socket_addrs
        
        self.num_worker = args.num_worker
        self.transfer_protocol = args.protocol

        self.current_jobnum = 0
        self.maximum_jobnum = 0
        self.total_processed = 0

        # auto scaling policy
        self.busy_util_threshold = args.busy_util_threshold
        self.duration_expand = args.duration_expand
        self.duration_squeeze = args.duration_squeeze
        self.util_check_interval_ms = 5*1000 # each 5s
        self.busycheck_history_num_sample = self.duration_expand//self.util_check_interval_ms
        self.squeezecheck_history_num_sample = self.duration_squeeze//self.util_check_interval_ms
        self.util_last_check_timestamp = time.time()
        self.expand_last_check_timestamp = time.time()
        self.squeeze_last_check_timestamp = time.time()
        self.system_squeezed = True
        self.util_history = []

        self.logdir = args.log_dir
        self.logger = set_logger(colored('SINK', 'green'), logger_dir=self.logdir, verbose=args.verbose)

    def close(self):
        self.logger.info('shutting down...')
        self.is_ready.clear()
        self.exit_flag.set()
        self.terminate()
        self.join()
        self.logger.info('terminated!')

    def run(self):
        self._run()

    def get_ideal_maxload(self, statistic_status):
        if self.total_processed == 0:
            return 0
        # calculate utils
        per_request_processing_time = np.mean(statistic_status._other_statistic['sys_predict'])
        # note that maximum_request_per_second is in the ideal condition, not considered data transfer overheat
        maximum_request_per_second = self.num_worker*(1000/per_request_processing_time)
        return maximum_request_per_second

    def get_current_utils(self, statistic_status):
        if self.total_processed == 0:
            return 0
            
        maximum_request_per_second = self.get_ideal_maxload(statistic_status)
        current_util = max(0, min(1, self.current_jobnum/maximum_request_per_second))
        return current_util

    def check_internal_utils(self, statistic_status, navigator_sink, logger):

        if self.total_processed < 10:
            return

        current_timestamp = time.time()
        current_interval = (current_timestamp - self.util_last_check_timestamp)*1000

        if current_interval>= self.util_check_interval_ms:

            current_util = self.get_current_utils(statistic_status)
            
            # logging time interval
            self.util_history.append([current_interval, current_util])
            self.util_last_check_timestamp = current_timestamp

            # only save enough sample to check
            # logger.warning("Utils check, num sample: {} util mean: {}".format(len(self.util_history), np.mean([a[1] for a in self.util_history])))
            if len(self.util_history) > self.squeezecheck_history_num_sample:
                self.util_history.pop(0)

            # checking if server is busy
            busycheck_histories = self.util_history[-self.busycheck_history_num_sample:]
            # logger.warning('Checking expand_worker, num sample: {} util mean: {}'.format(len(busycheck_histories), np.mean([a[1] for a in busycheck_histories])))
            if ((current_timestamp-self.expand_last_check_timestamp)*1000) >= self.duration_expand \
                and len(busycheck_histories) == self.busycheck_history_num_sample \
                and np.mean(np.array([a[1] for a in busycheck_histories]))>=self.busy_util_threshold:
                # service is really busy
                # logger.warning('SENT expand_worker, num sample: {} util mean: {}'.format(len(busycheck_histories), np.mean([a[1] for a in busycheck_histories])))
                navigator_sink.send(ServerCmd.expand_worker)

                self.system_squeezed = False
                # reset timer for the next checking
                self.expand_last_check_timestamp = current_timestamp
                self.squeeze_last_check_timestamp = current_timestamp

            elif ((current_timestamp-self.squeeze_last_check_timestamp)*1000) >= self.duration_squeeze \
                and not self.system_squeezed:
                # if server not busy, check if it is free enough
                squeezecheck_histories = self.util_history[-self.squeezecheck_history_num_sample:]
                # logger.warning('Checking squeeze_worker, num sample: {} util mean: {}'.format(len(squeezecheck_histories), np.mean([a[1] for a in squeezecheck_histories])))
                if len(squeezecheck_histories) == self.squeezecheck_history_num_sample \
                    and np.mean(np.array([a[1] for a in squeezecheck_histories])) < self.busy_util_threshold:
                    # service is not quite busy
                    # logger.warning('SENT squeeze_worker, num sample: {} util mean: {}'.format(len(squeezecheck_histories), np.mean([a[1] for a in squeezecheck_histories])))
                    navigator_sink.send(ServerCmd.squeeze_worker)

                    self.system_squeezed = True
                    # reset timer for the next checking
                    self.expand_last_check_timestamp = current_timestamp
                    self.squeeze_last_check_timestamp = current_timestamp
        else:
            # nothing to check when not in checking interval
            pass
        
    @zmqd.socket(zmq.PULL)
    @zmqd.socket(zmq.PAIR)
    @zmqd.socket(zmq.PUB)
    def _run(self, receiver, frontend, sender):

        receiver_addr = auto_bind(receiver)
        frontend.connect(self.nav_to_sink_addr)
        sender.bind('tcp://*:%d' % self.port)

        poller = zmq.Poller()
        poller.register(frontend, zmq.POLLIN)
        poller.register(receiver, zmq.POLLIN)

        # send worker receiver address back to frontend
        frontend.send(receiver_addr.encode('ascii'))
        
        # Windows does not support logger in MP environment, thus get a new logger
        # inside the process for better compability
        logger = set_logger(colored('SINK', 'green'), logger_dir=self.logdir, verbose=self.verbose)
        logger_error = set_logger(colored('SINK-ERROR', 'red'), logger_dir=self.logdir, verbose=self.verbose, error_log=True)
        logger.info('ready')
        self.is_ready.set()

        sink_status = ServerStatistic()
        latency_status = defaultdict(lambda: {'start': -1, 'end': -1})

        def check_status(sink_status, latency_status):
            result = []
            removed_keys = []
            for k, status in latency_status.items():
                if status['start'] != -1 and status['end'] != -1:
                    latency = (status['end']-status['start'])*1000
                    result.append(latency)
                    removed_keys.append(k)
            for k in removed_keys:
                latency_status.pop(k)
            for res in result:
                sink_status.update_key('latency', res)
            # print('\n',dict(latency_status), '\n', result, '\n')

        while not self.exit_flag.is_set():
            try:
                socks = dict(poller.poll(1000))

                if socks.get(receiver) == zmq.POLLIN:
                    client, req_id, msg, msg_info = recv_from_prev_raw(receiver)

                    if msg_info == ServerCmd.statistic:
                        # record statistic value
                        stat_info = jsonapi.loads(msg)
                        for k, v in stat_info.items():
                            sink_status.update_key(k, v)
                        logger.info('Update statistic\tjob id: {}#{}'.format(client, req_id))
                    else:
                        # main processing flow
                        if msg_info == ServerCmd.exception:
                            # exception
                            logger_error.error("exception processing {}#{}\n{}".format(client, req_id, msg))
                            sink_status.update([
                                to_bytes(client), 
                                ServerCmd.exception, 
                                to_bytes(req_id), 
                                b'1'
                            ])
                        else:
                            # embeding
                            logger.info("collected {}#{}".format(client, req_id))
                            sink_status.update([
                                to_bytes(client), 
                                b'<new_request>', 
                                to_bytes(req_id), 
                                b'1'
                            ])
                        sink_status.update_key('sys_output_byte', len(msg))

                        send_to_next_raw(client, req_id, msg, msg_info, sender)

                        # update latency
                        job_id = to_str(client) + '#' + to_str(req_id)
                        latency_status[job_id]['end'] = time.time()
                        check_status(sink_status, latency_status)

                        self.current_jobnum -= 1
                        self.total_processed += 1
                        logger.info('send back\tjob id: {}#{} \tleft: {}'.format(client, req_id, self.current_jobnum))

                if socks.get(frontend) == zmq.POLLIN:
                    request = frontend.recv_multipart()
                    client_addr, msg_type, msg_info, req_id = request
                    if msg_type == ServerCmd.new_job:
                        job_id = to_str(client_addr) + '#' + to_str(req_id)
                        self.current_jobnum += 1
                        self.maximum_jobnum = max(self.current_jobnum, self.maximum_jobnum)
                        job_info = jsonapi.loads(msg_info)

                        # update latency
                        latency_status[job_id]['start'] = job_info['time']
                        check_status(sink_status, latency_status)
                        sink_status.update_key('sys_input_byte', job_info['input_byte'])

                        logger.info('registed job\tjob id: {}\tleft: {}'.format(job_id, self.current_jobnum))

                    elif msg_type == ServerCmd.show_config:
                        time.sleep(0.1)  # dirty fix of slow-joiner: sleep so that client receiver can connect.
                        sink_status.update(request)
                        logger.info('send config\tclient %s' % client_addr)
                        prev_status = jsonapi.loads(msg_info)
                        
                        ideal_maxload = self.get_ideal_maxload(sink_status)
                        current_util = self.get_current_utils(sink_status)
                        status={
                            'statistic_postsink': {**{
                                'total_job_in_queue': self.current_jobnum,
                                'maximum_job_in_queue': self.maximum_jobnum,
                                'total_processed_job': self.total_processed,
                                'util': current_util,
                                'ideal_maxload': ideal_maxload,
                            }, **sink_status.value}
                        }
                        send_to_next('obj', client_addr, req_id, {**prev_status, **status}, sender)
                    elif msg_type == ServerCmd.exception:
                        # not yet registed to the server
                        send_to_next_raw(client_addr, req_id, msg_info, ServerCmd.exception, sender)
                        logger_error.error("exception received {}#{}\{}".format(client_addr, req_id, msg_info))

                self.check_internal_utils(sink_status, frontend, logger)

            except Exception as e:
                logger_error.error('{}'.format(e), exc_info=True)
