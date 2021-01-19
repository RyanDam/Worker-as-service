import sys
import threading
import time
import uuid
import warnings
from collections import namedtuple
from functools import wraps

import numpy as np
import zmq
import zmq.decorators as zmqd
from zmq.utils import jsonapi
import threading
import multiprocessing 
from multiprocessing import Process
from termcolor import colored

from .helper import *
from .protocol import *

__all__ = ['WKRWorker', 'WKRDecentralizeCentral']

class WKRWorker(Process):
    
    def __init__(self, idx, ip, port, port_out, logdir=None):
        super().__init__()
        self.logger = set_logger(colored('WORKER-{}-{:03d}'.format(ip, idx), 'green'), logger_dir=logdir)
        self.idx = idx
        self.ip = ip
        self.port = port
        self.port_out = port_out
        self.logdir = logdir
        self.exit_flag = multiprocessing.Event()
        self.is_ready = multiprocessing.Event()

    def close(self):
        self.logger.info('Shutting down...')
        self.exit_flag.set()
        # self.terminate()
        self.join()
        self.logger.info('terminated!')
    
    def get_model(self, ip, port, port_out):
        raise NotImplementedError('WKRWorker:get_model() not implemented')

    def do_work(self, model, logger):
        raise NotImplementedError('WKRWorker:do_work() not implemented')

    def off_model(self, model):
        raise NotImplementedError('WKRWorker:off_model() not implemented')

    def run(self):
        # logger = set_logger(colored('WORKER-{}-{:03d}'.format(self.ip, self.idx), 'green'), logger_dir=self.logdir)

        # logger = set_logger(colored('WORKER-{}-{:03d}'.format(self.ip, self.idx), 'green'), logger_dir=self.logdir)
        logger = LoggerSeperate('WORKER-{}-{:03d}'.format(self.ip, self.idx), 'green', logger_dir=self.logdir)

        model = self.get_model(self.ip, self.port, self.port_out)

        self.is_ready.set()
        logger.info('INIT DONE\tidx: {}\tip: {}\tport: {}\tport_out: {}'.format(self.idx, self.ip, self.port, self.port_out))

        while not self.exit_flag.is_set():

            try:
                self.do_work(model, logger)
            except Exception as e:
                logger.error('error: {}'.format(e))

            time.sleep(0.03) # sleep 3ms

        self.off_model(model)
        logger.info('EXITED')

class WKRDecentralizeCentral(threading.Thread):

    def __init__(self, worker_skeleton, args):
        super().__init__()
        self.worker_skeleton = worker_skeleton
        if not issubclass(self.worker_skeleton, WKRWorker):
            raise AssertionError('worker_skeleton must inherit from class WKRWorker')
        
        self.args = args
        self.logdir = args.log_dir
        self.logger = set_logger(colored('CENTRAL', 'red'), logger_dir=self.logdir)
        self.port = args.port
        self.port_out = args.port_out
        self.number_client = args.num_client
        self.remote_servers = args.remote_servers
        self.all_processes = []
        self.is_ready = threading.Event()

    def __enter__(self):
        self.start()
        self.is_ready.wait()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    @staticmethod
    def terminate(args):
        with zmq.Context() as ctx:
            ctx.setsockopt(zmq.LINGER, args.timeout)
            with ctx.socket(zmq.PUSH) as frontend:
                try:
                    frontend.connect('tcp://%s:%d' % (args.ip, args.port))
                    frontend.send_multipart([ServerCmd.terminate, b''])
                    print('shutdown signal sent to %d' % args.port)
                except zmq.error.Again:
                    raise TimeoutError(
                        'no response from the server (with "timeout"=%d ms), please check the following:'
                        'is the server still online? is the network broken? are "port" correct? ' % args.timeout)

    @staticmethod
    def idle(args):
        with zmq.Context() as ctx:
            ctx.setsockopt(zmq.LINGER, args.timeout)
            with ctx.socket(zmq.PUSH) as frontend:
                try:
                    frontend.connect('tcp://%s:%d' % (args.ip, args.port))
                    frontend.send_multipart([ServerCmd.idle_mode, b''])
                    print('idle signal sent to %d' % args.port)
                except zmq.error.Again:
                    raise TimeoutError(
                        'no response from the server (with "timeout"=%d ms), please check the following:'
                        'is the server still online? is the network broken? are "port" correct? ' % args.timeout)

    @staticmethod
    def restart_clients(args):
        with zmq.Context() as ctx:
            ctx.setsockopt(zmq.LINGER, args.timeout)
            with ctx.socket(zmq.PUSH) as frontend:
                try:
                    frontend.connect('tcp://%s:%d' % (args.ip, args.port))
                    frontend.send_multipart([ServerCmd.restart_client, b''])
                    print('idle signal sent to %d' % args.port)
                except zmq.error.Again:
                    raise TimeoutError(
                        'no response from the server (with "timeout"=%d ms), please check the following:'
                        'is the server still online? is the network broken? are "port" correct? ' % args.timeout)

    @staticmethod
    def switch_server(args):
        with zmq.Context() as ctx:
            ctx.setsockopt(zmq.LINGER, args.timeout)
            with ctx.socket(zmq.PUSH) as frontend, ctx.socket(zmq.PULL) as receiver:
                try:
                    frontend.connect('tcp://%s:%d' % (args.ip, args.port))
                    receiver.connect('tcp://%s:%d' % (args.ip, args.port_out)),
                    frontend.send_multipart([ServerCmd.switch_server, jsonapi.dumps({'remote_servers':args.remote_servers, 'number_clients': args.num_client})])
                    print('Switch server signal sent to %d' % args.port)
                    result = receiver.recv()
                    print('Switch server successful with result', jsonapi.loads(result))
                except zmq.error.Again:
                    raise TimeoutError(
                        'no response from the server (with "timeout"=%d ms), please check the following:'
                        'is the server still online? is the network broken? are "port" correct? ' % args.timeout)

    @staticmethod
    def show_config(args):
        with zmq.Context() as ctx:
            ctx.setsockopt(zmq.LINGER, args.timeout)
            with ctx.socket(zmq.PUSH) as frontend, ctx.socket(zmq.PULL) as receiver:
                try:
                    frontend.connect('tcp://%s:%d' % (args.ip, args.port))
                    receiver.connect('tcp://%s:%d' % (args.ip, args.port_out)),
                    frontend.send_multipart([ServerCmd.show_config, b''])
                    print('Show config server signal sent to %d' % args.port)
                    result = receiver.recv()
                    print('Current server config:\n{}'.format(jsonapi.loads(result)))
                except zmq.error.Again:
                    raise TimeoutError(
                        'no response from the server (with "timeout"=%d ms), please check the following:'
                        'is the server still online? is the network broken? are "port" correct? ' % args.timeout)

    def close(self):
        self.logger.info('Main handler shutting down...')
        self._send_close_signal()
        self.is_ready.clear()
        self.join()

    @zmqd.context()
    @zmqd.socket(zmq.PUSH)
    def _send_close_signal(self, _, frontend):
        frontend.connect('tcp://localhost:%d' % self.port)
        frontend.send_multipart([ServerCmd.terminate, b''])

    def run(self):
        self._run()

    @zmqd.context()
    @zmqd.socket(zmq.PULL)
    @zmqd.socket(zmq.PUSH)
    def _run(self, _, frontend, sender):
        logger = set_logger(colored('CENTRAL', 'red'), logger_dir=self.logdir)

        self.logger.info('bind all sockets')
        frontend.bind('tcp://*:%d' % self.port)
        sender.bind('tcp://*:%d' % self.port_out)

        def kill_current_clients():
            for client in self.all_processes:
                client.close()
            
            if len(self.all_processes) > 0:
                logger.info('main handler clients are killed...')
                self.all_processes= []

        def start_client(remote_server):
            host = remote_server[0]
            port = remote_server[1]
            port_out = remote_server[2]
            for i in range(self.number_client):
                client = self.worker_skeleton(i, host, port, port_out, logdir=self.logdir)
                self.all_processes.append(client)
                client.start()
        
        def start_clients():
            for remote_server in self.remote_servers:
                start_client(remote_server)

        def restart_clients():
            logger.info('restarting clients...')
            kill_current_clients()
            start_clients()

        logger.info('main handler starting...')

        start_clients()

        for p in self.all_processes:
            p.is_ready.wait()

        self.is_ready.set()
        logger.info('all set, ready to serve request!')

        while True:
            try:
                request = frontend.recv_multipart()
                msg, msg_cmd = request
            except (ValueError, AssertionError):
                logger.error('received a wrongly-formatted request (expected 2 frames, got %d)' % len(request))
                logger.error('\n'.join('field %d: %s' % (idx, k) for idx, k in enumerate(request)), exc_info=True)
            else:
                if msg == ServerCmd.terminate:
                    logger.info('new terminate request')
                    break
                if msg == ServerCmd.idle_mode:
                    logger.info('new idle request')
                    kill_current_clients()
                if msg == ServerCmd.restart_client:
                    logger.info('new restart client request')
                    restart_clients()
                elif msg == ServerCmd.show_config:
                    logger.info('new config request')
                    sender.send(jsonapi.dumps({'port': self.port, 
                                                'port_out': self.port_out, 
                                                'number_client_per_server': self.number_client,
                                                'remote_servers': self.remote_servers}))
                elif msg == ServerCmd.switch_server:
                    logger.info('new switch remote server request')
                    try:
                        new_config = jsonapi.loads(msg_cmd)
                        
                    except Exception as e:
                        logger.error('received a wrongly-formatted remote server config: {}'.format(msg_cmd))
                    new_remote_server = new_config['remote_servers']
                    new_client_number = new_config['number_clients']
                    if new_remote_server:
                        self.remote_servers = new_remote_server
                    if new_client_number > 0:
                        self.number_client = new_client_number
                    restart_clients()
                    sender.send(jsonapi.dumps({'success': True}))
                else:
                    logger.error('received a wrongly-formatted request: {}'.format(request))

        kill_current_clients()
        logger.info('terminated!')