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

from .postsink import WKRSink
from .hard_worker import WKRHardWorker
from .statistic import ServerStatistic

__all__ = ['__version__', 'WKRServer', 'WKRHardWorker']
__version__ = '2.0.1'

class WKRServer(threading.Thread):
    def __init__(self, args, hardprocesser=None, httpprocessor=None):
        super().__init__()
        
        if hardprocesser is None:
            hardprocesser = WKRHardWorker

        if httpprocessor is None:
            httpprocessor = BertHTTPProxy

        self.hardprocessor_skeleton = hardprocesser
        if not issubclass(self.hardprocessor_skeleton, WKRHardWorker):
            raise AssertionError('hardprocesser must inherit from class WKRHardWorker')

        self.httpprocessor_skeleton = httpprocessor

        self.model_dir = args.model_dir

        self.num_worker = args.num_worker
        self.device_map = args.device_map
        self.gpu_memory_fraction = args.gpu_memory_fraction
        self.all_cpu = args.cpu

        self.num_concurrent_postsocket = max(8, args.num_worker * 2)
        self.batch_size = args.batch_size

        self.total_concurrent_socket = self.num_concurrent_postsocket

        self.port = args.port
        self.args = args
        self.transfer_protocol = args.protocol

        self.status_args = {k: v for k, v in sorted(vars(args).items())}
        self.status_static = {
            'python_version': sys.version,
            'server_version': __version__,
            'pyzmq_version': zmq.pyzmq_version(),
            'zmq_version': zmq.zmq_version(),
            'server_start_time': str(datetime.now()),
        }
        self.processes = []
        self.process_workers = []
        self.process_expanded_workers = []

        # auto scaling policy
        self.num_worker_to_expand = args.num_worker_expanded
        self.device_to_expand = args.device_to_expand

        # logging 
        self.logdir = args.log_dir
        self.logger = set_logger(colored('NAVIGATOR', 'red'), logger_dir=self.logdir, verbose=args.verbose)
        self.server_all_terminated = False

        self.is_ready = threading.Event()

    def __enter__(self):
        self.start()
        self.is_ready.wait()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def close(self):
        self.logger.info('shutting down...')
        if not self.server_all_terminated:
            self._send_close_signal()
        else:
            # already terminated, no need to send the signal again
            pass
        self.is_ready.clear()
        self.join()

    @zmqd.context()
    @zmqd.socket(zmq.PUSH)
    def _send_close_signal(self, _, frontend):
        frontend.connect('tcp://localhost:%d' % self.port)
        frontend.send_multipart([b'', b'', ServerCmd.terminate, b''])

    @staticmethod
    def shutdown(args):
        with zmq.Context() as ctx:
            ctx.setsockopt(zmq.LINGER, args.timeout)
            with ctx.socket(zmq.PUSH) as frontend:
                try:
                    frontend.connect('tcp://%s:%d' % (args.ip, args.port))
                    frontend.send_multipart([b'', b'', ServerCmd.terminate, b''])
                    print('shutdown signal sent to %d' % args.port)
                except zmq.error.Again:
                    raise TimeoutError(
                        'no response from the server (with "timeout"=%d ms), please check the following:'
                        'is the server still online? is the network broken? are "port" correct? ' % args.timeout)

    def generate_worker_process(self, args, worker_id, addr_backend_post_list, addr_sink, device_id):
        process = self.hardprocessor_skeleton(worker_id, self.args, addr_backend_post_list, addr_sink, device_id)
        return process

    def close_all_worker(self):
        # exited, close all child process
        for p in self.process_workers:
            p.close()
        self.process_workers = []

    def start_all_worker(self, addr_backend_post_list, addr_sink):
        self.device_map_main_worker = self._get_device_map(self.num_worker, self.device_map, self.gpu_memory_fraction, run_all_cpu=self.all_cpu)
        for idx, device_id in enumerate(self.device_map_main_worker):
            process = self.generate_worker_process(self.args, idx, addr_backend_post_list, addr_sink, device_id)
            self.process_workers.append(process)
            process.start()

    def restart_all_worker(self, addr_backend_post_list, addr_sink):
        self.close_all_worker()
        self.start_all_worker(addr_backend_post_list, addr_sink)
        for p in self.process_workers:
            p.is_ready.wait()

    def expand_worker(self, addr_backend_post_list, addr_sink):
        current_expanded_worker = len(self.process_expanded_workers)
        self.logger.warning(f"expand_worker command received, current number expaned worker: {current_expanded_worker}")

        if current_expanded_worker >= self.num_worker_to_expand:
            self.logger.warning(f"current number of expanded worker ({current_expanded_worker}) is exeed assigned number ({self.num_worker_to_expand})")
        else:
            target_expand_device = self._get_expandable_device(self.device_to_expand, self.gpu_memory_fraction)
            if target_expand_device is None:
                self.logger.warning(f"trying to expand worker but no more GPU device is available, looked at devices: {self.device_to_expand} with at least {self.gpu_memory_fraction*100:0.1f}% memory available")
            else:
                target_expanded_worker_id = f"E{time.time()}"
                process = self.generate_worker_process(self.args, target_expanded_worker_id, addr_backend_post_list, addr_sink, target_expand_device)
                self.process_expanded_workers.append(process)
                process.start()
                self.logger.warning(f"started 1 WORKER-{target_expanded_worker_id} at GPU {target_expand_device}")

    def squeeze_worker(self):
        self.logger.warning("squeeze_worker command received")
        # kill all expanded worker
        closed_expanded_worker = 0
        for p in self.process_expanded_workers:
            p.close()
            closed_expanded_worker += 1
        self.process_expanded_workers = []
        self.logger.warning(f"killed {closed_expanded_worker} expanded worker")

    def run(self):
        self._run()

    @zmqd.context()
    @zmqd.socket(zmq.PULL)
    @zmqd.socket(zmq.PAIR)
    @multi_socket(zmq.PUSH, num_socket='total_concurrent_socket')
    def _run(self, _, frontend, sink, *backend_socks):

        def push_new_job(client, req_id, msg_raw, msg_info_raw):
            # start = time.time()
            _sock = rand_backend_socket
            send_to_next_raw(client, req_id, msg_raw, msg_info_raw, _sock)
            # end = time.time()
            # self.logger.warning("Push to worker: {}".format(end-start))

        # bind all sockets
        self.logger.info('bind all sockets')
        frontend.bind('tcp://*:%d' % self.port)
        addr_front2sink = auto_bind(sink)

        addr_backend_post_list = [auto_bind(b) for b in backend_socks]
        self.logger.info('open %d worker sockets' % len(addr_backend_post_list))

        # start the sink process
        self.logger.info('start the sink')
        proc_postsink = WKRSink(self.args, addr_front2sink, addr_backend_post_list)
        self.processes.append(proc_postsink)
        proc_postsink.start()
        addr_sink = sink.recv().decode('ascii')

        # start the post-backend processes
        # WaveWorker: self, id, args, worker_address_list, sink_address, device_id
        self.logger.info('start main-workers')
        self.start_all_worker(addr_backend_post_list, addr_sink)

        # start the http-service process
        if self.args.http_port:
            self.logger.info('start http proxy')
            proc_proxy = self.httpprocessor_skeleton(self.args)
            self.processes.append(proc_proxy)
            proc_proxy.start()

        rand_backend_socket = None
        server_status = ServerStatistic()
        
        for p in [*self.processes, *self.process_workers]:
            p.is_ready.wait()

        self.is_ready.set()
        self.logger.info('all set, ready to serve request!')

        poller = zmq.Poller()
        poller.register(frontend, zmq.POLLIN)
        poller.register(sink, zmq.POLLIN)

        while True:
            socks = dict(poller.poll())

            if socks.get(frontend) == zmq.POLLIN:
                try:
                    request = frontend.recv_multipart()
                    client, req_id, msg, msg_info = request
                    # client, req_id, msg, msg_info = recv_from_prev(self.transfer_protocol, frontend)
                    # request = [client, msg, req_id, msg_info]
                except (ValueError, AssertionError):
                    exception_msg = 'received a wrongly-formatted request (expected 4 frames, got %d)' % len(request)
                    self.logger.error(exception_msg)
                    self.logger.error('\n'.join('field %d: %s' % (idx, k) for idx, k in enumerate(request)), exc_info=True)
                    sink.send_multipart([client, ServerCmd.exception, to_bytes(exception_msg), to_bytes(req_id)])
                else:
                    server_status.update(request)
                    if msg == ServerCmd.terminate:
                        break
                    elif msg == ServerCmd.show_config:
                        self.logger.info('new config request\treq id: %d\tclient: %s' % (int(req_id), client))
                        status_runtime = {'client': client.decode('ascii'),
                                        'num_process': len(self.processes) + len(self.process_workers),
                                        'num_worker_process': len(self.process_workers),
                                        'num_expanded_worker_process': len(self.process_expanded_workers),
                                        'navigator -> worker': addr_backend_post_list,
                                        'worker -> sink': addr_sink,
                                        'server_current_time': str(datetime.now()),
                                        'statistic': server_status.value,
                                        'main_device_map': self.device_map_main_worker,
                                        'main_batch_size': self.batch_size,
                                        'protocol': self.transfer_protocol,
                                        'num_concurrent_socket': self.total_concurrent_socket}
                        sink.send_multipart([client, msg, jsonapi.dumps({**status_runtime,
                                                                        **self.status_args,
                                                                        **self.status_static}), req_id])
                    else:
                        self.logger.info('new encode request\treq id: %s\tclient: %s' %
                                        (str(req_id), client))

                        # regist job
                        sink.send_multipart([client, ServerCmd.new_job, 
                                            jsonapi.dumps({
                                                'job_parts': '1', 
                                                'split_info': {}, 
                                                'time': time.time(),
                                                'input_byte': len(msg)
                                            }), to_bytes(req_id)])

                        # pick random socket
                        rand_backend_socket = random.choice([b for b in backend_socks if b != rand_backend_socket])

                        # push job
                        push_new_job(client, req_id, msg, msg_info)
            
            if socks.get(sink) == zmq.POLLIN:
                try:
                    command = sink.recv()
                    if command == ServerCmd.expand_worker:
                        self.expand_worker(addr_backend_post_list, addr_sink)
                    elif command == ServerCmd.squeeze_worker:
                        self.squeeze_worker()
                except Exception as e:
                    self.logger.error(e)
                
        # exited, close all child process
        for p in [*self.processes, *self.process_workers]:
            p.close()

        self.logger.info('terminated!')
        self.server_all_terminated = True

    def _get_device_map(self, num_worker, device_map_raw, per_process_gpu_fragment, run_all_cpu=False):
        self.logger.info('get devices map')
        run_on_gpu = False
        device_map = [-1] * num_worker

        if not run_all_cpu:
            try:
                import GPUtil
                num_all_gpu = len(GPUtil.getGPUs())
                avail_gpu = GPUtil.getAvailable(order='memory', limit=min(num_all_gpu, num_worker),
                                                maxMemory=1-per_process_gpu_fragment, maxLoad=0.9)
                num_avail_gpu = len(avail_gpu)
                if num_avail_gpu >= num_worker:
                    run_on_gpu = True
                elif 0 < num_avail_gpu < num_worker:
                    self.logger.warning('only %d out of %d GPU(s) is available/free, but "num_worker=%d"' %
                                        (num_avail_gpu, num_all_gpu, num_worker))
                    if not device_map_raw:
                        self.logger.warning('multiple workers will be allocated to one GPU, '
                                            'may not scale well and may raise out-of-memory')
                    else:
                        self.logger.warning('workers will be allocated based on "-device_map=%s", '
                                            'may not scale well and may raise out-of-memory' % device_map_raw)
                    run_on_gpu = True
                else:
                    self.logger.warning('no GPU available, fall back to CPU')
                
                if run_on_gpu:
                    device_map = ((device_map_raw or avail_gpu) * num_worker)[: num_worker]

            except FileNotFoundError:
                self.logger.warning('nvidia-smi is missing, often means no gpu on this machine. '
                                    'fall back to cpu!')
        
        self.logger.info('device map: \n\t\t%s' % '\n\t\t'.join(
            'worker %2d -> %s' % (w_id, ('gpu %2d' % g_id) if g_id >= 0 else 'cpu') for w_id, g_id in
            enumerate(device_map)))

        return device_map

    def _get_expandable_device(self, target_gpus, per_process_gpu_fragment):
        import GPUtil
        all_physic_gpu = [a.id for a in GPUtil.getGPUs()]
        excluded_gpus = []
        for gpu in all_physic_gpu:
            if gpu not in target_gpus:
                excluded_gpus.append(gpu)
        avail_gpu=GPUtil.getAvailable(order='memory', limit=1, maxMemory=1-(per_process_gpu_fragment*1.1), maxLoad=0.9, excludeID=excluded_gpus)
        if avail_gpu:
            return avail_gpu[0]
        else: 
            return None