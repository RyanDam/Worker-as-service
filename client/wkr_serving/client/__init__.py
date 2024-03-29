#!/usr/bin/env python
# -*- coding: utf-8 -*-
# Han Xiao <artex.xh@gmail.com> <https://hanxiao.github.io>

import sys
import threading
import time
import uuid
import warnings
from collections import namedtuple
from functools import wraps

import numpy as np
import zmq
from zmq.utils import jsonapi

from .protocol import *
from .decentralizedworker import *

__all__ = ['__version__', 'WKRClient', 'ConcurrentWKRClient', 'WKRWorker', 'WKRDecentralizeCenter']

# in the future client version must match with server version
__version__ = '2.1.0'

if sys.version_info >= (3, 0):
    from ._py3_var import *
else:
    from ._py2_var import *

_Response = namedtuple('_Response', ['id', 'content', 'error_raised'])
Response = namedtuple('Response', ['id', 'embedding', 'error_code', 'error_message'])

class WKRClient(object):
    def __init__(self, ip='localhost', port=5555, port_out=5556,
                 protocol='obj',
                 show_server_config=False, identity=None, 
                 check_version=True, check_length=False,
                 ignore_all_checks=False,
                 timeout=15*60*1000): # 4*60*1000 timeout after 4m, default is -1, mean forever

        """ A client object connected to a TTSServer

        Create a WKRClient that connects to a TTSServer.
        Note, server must be ready at the moment you are calling this function.
        If you are not sure whether the server is ready, then please set `ignore_all_checks=True`

        You can also use it as a context manager:

        .. highlight:: python
        .. code-block:: python

            with WKRClient() as bc:
                bc.encode(...)

            # bc is automatically closed out of the context

        :type timeout: int
        :type check_version: bool
        :type check_length: bool
        :type ignore_all_checks: bool
        :type identity: str
        :type show_server_config: bool
        :type output_fmt: str
        :type port_out: int
        :type port: int
        :type ip: str
        :param ip: the ip address of the server
        :param port: port for pushing data from client to server, must be consistent with the server side config
        :param port_out: port for publishing results from server to client, must be consistent with the server side config
        :param output_fmt: the output format of the sentence encodes, either in numpy array or python List[List[float]] (ndarray/list)
        :param show_server_config: whether to show server configs when first connected
        :param identity: the UUID of this client
        :param check_version: check if server has the same version as client, raise AttributeError if not the same
        :param check_length: check if server `max_seq_len` is less than the sentence length before sent
        :param ignore_all_checks: ignore all checks, set it to True if you are not sure whether the server is ready when constructing WKRClient()
        :param timeout: set the timeout (milliseconds) for receive operation on the client, -1 means no timeout and wait until result returns
        """

        self.context = zmq.Context()
        self.sender = self.context.socket(zmq.PUSH)
        self.sender.setsockopt(zmq.LINGER, 0)
        self.identity = identity or str(uuid.uuid4()).encode('ascii')
        self.sender.connect('tcp://%s:%d' % (ip, port))

        self.receiver = self.context.socket(zmq.SUB)
        self.receiver.setsockopt(zmq.LINGER, 0)
        self.receiver.setsockopt(zmq.SUBSCRIBE, self.identity)
        self.receiver.connect('tcp://%s:%d' % (ip, port_out))

        self.request_id = 0
        self.timeout = timeout
        self.pending_request = set()
        self.pending_response = {}

        if protocol not in ['obj', 'numpy']:
            raise AttributeError('"protocol" must be "obj" or "numpy"')

        self.protocol = protocol

        self.port = port
        self.port_out = port_out
        self.ip = ip
        self.length_limit = 0
        self.token_info_available = False

        if not ignore_all_checks:
            s_status = self.server_status
            if s_status['protocol'] != self.protocol:
                raise AttributeError('Protocol mismatch. Target server using protocol "{}" while this client use "{}"'.format(s_status['protocol'], self.protocol))

        if not ignore_all_checks and (check_version or show_server_config or check_length):
            if check_version and s_status['server_version'] != self.status['client_version']:
                raise AttributeError('version mismatch! server version is %s but client version is %s!\n'
                                     'consider "pip install -U tts-serving-server tts-serving-client"\n'
                                     'or disable version-check by "WKRClient(check_version=False)"' % (
                                         s_status['server_version'], self.status['client_version']))

            if check_length:
                if s_status['target_max_seq_len'] is not None:
                    self.length_limit = int(s_status['target_max_seq_len'])
                else:
                    self.length_limit = None

            if show_server_config:
                self._print_dict(s_status, 'server config:')

    def close(self):
        """
            Gently close all connections of the client. If you are using WKRClient as context manager,
            then this is not necessary.
        """
        # self.sender.close()
        # self.receiver.close()
        self.sender.close(0)
        self.receiver.close(0)
        self.context.term()

    def _send(self, msg, target_request_id=None):
        self.request_id += 1
        req_id = target_request_id if target_request_id else self.request_id
        req_id = str(req_id)

        if msg in [ServerCmd.terminate, ServerCmd.show_config]:
            send_to_next_raw(self.identity, req_id, msg, jsonapi.dumps('{}'), self.sender)
        else:
            send_to_next(self.protocol, self.identity, req_id, msg, self.sender)

        # print(req_id)
        self.pending_request.add(req_id)
        return req_id

    def _recv(self, wait_for_req_id=None, force_protocol=None):
        if force_protocol != None:
            assert force_protocol in ['obj', 'numpy'], 'force_protocol must be one of ["obj","numpy"]'

        try:
            wait_for_req_id = str(wait_for_req_id) if wait_for_req_id else None
            while True:
                # a request has been returned and found in pending_response
                if wait_for_req_id in self.pending_response:
                    response, raised_error = self.pending_response.pop(wait_for_req_id)
                    return _Response(wait_for_req_id, response, raised_error)

                # receive a response
                protocol = force_protocol if force_protocol != None else self.protocol
                raised_error = False
                try:
                    client, req_id, msg, msg_info = recv_from_prev(protocol, self.receiver)
                except ProcessingError as e:
                    client, req_id, msg = e.client_id, e.req_id, e.raw_msg
                    raised_error = True
                except Exception as e:
                    raise e

                request_id = str(req_id)

                # print(request_id)
                # if not wait for particular response then simply return
                if not wait_for_req_id or (wait_for_req_id == request_id):
                    # print(self.pending_request, request_id)
                    if request_id in self.pending_request:
                        self.pending_request.remove(request_id)
                    return _Response(request_id, msg, raised_error)
                elif wait_for_req_id != request_id:
                    self.pending_response[request_id] = msg, raised_error
                    # wait for the next response
        except Exception as e:
            raise e
        finally:
            if wait_for_req_id in self.pending_request:
                self.pending_request.remove(wait_for_req_id)

    def _recv_ndarray(self, wait_for_req_id=None):
        request_id, response, error_raised = self._recv(wait_for_req_id)
        if error_raised:
            return Response(request_id, None, 1, response)
        else:
            return Response(request_id, response, 0, 'success')


    @property
    def status(self):
        """
            Get the status of this WKRClient instance

        :rtype: dict[str, str]
        :return: a dictionary contains the status of this WKRClient instance

        """
        return {
            'identity': self.identity,
            'num_request': self.request_id,
            'num_pending_request': len(self.pending_request),
            'pending_request': self.pending_request,
            'port': self.port,
            'port_out': self.port_out,
            'server_ip': self.ip,
            'client_version': __version__,
            'timeout': self.timeout
        }

    def _timeout(func):
        @wraps(func)
        def arg_wrapper(self, *args, **kwargs):
            if 'blocking' in kwargs and not kwargs['blocking']:
                # override client timeout setting if `func` is called in non-blocking way
                self.sender.setsockopt(zmq.SNDTIMEO, -1)
                self.receiver.setsockopt(zmq.RCVTIMEO, -1)
            else:
                self.sender.setsockopt(zmq.SNDTIMEO, self.timeout)
                self.receiver.setsockopt(zmq.RCVTIMEO, self.timeout)
            try:
                return func(self, *args, **kwargs)
            except zmq.error.Again as _e:
                t_e = TimeoutError(
                    '''no response from the server (with "timeout"={} ms), please check the following:
                    is the server still online? is the network broken? are "port" and "port_out" correct? 
                    are you encoding a huge amount of data whereas the timeout is too small for that?\nRequest id:{}'''.format(
                        self.timeout, "{}#{}:{}".format(self.identity, self.request_id, ','.join(self.pending_request))
                    ))
                if _py2:
                    raise t_e
                else:
                    _raise(t_e, _e)
            finally:
                self.sender.setsockopt(zmq.SNDTIMEO, -1)
                self.receiver.setsockopt(zmq.RCVTIMEO, -1)

        return arg_wrapper

    @property
    @_timeout
    def server_status(self):
        """
            Get the current status of the server connected to this client

        :return: a dictionary contains the current status of the server connected to this client
        :rtype: dict[str, str]

        """
        req_id = self._send(b'SHOW_CONFIG')
        data = self._recv(req_id, force_protocol='obj')
        return data.content

    @_timeout
    def encode(self, data, blocking=True, target_request_id=None):
        
        req_id = self._send(data, target_request_id=target_request_id)

        if not blocking:
            return None

        r = self._recv_ndarray(req_id)
        if r.error_code == 0:
            return r.embedding
        else:
            raise Exception(r.error_message)

    def fetch(self, delay=.0):
        """ Fetch the encoded vectors from server, use it with `encode(blocking=False)`

        Use it after `encode(texts, blocking=False)`. If there is no pending requests, will return None.
        Note that `fetch()` does not preserve the order of the requests! Say you have two non-blocking requests,
        R1 and R2, where R1 with 256 samples, R2 with 1 samples. It could be that R2 returns first.

        To fetch all results in the original sending order, please use `fetch_all(sort=True)`

        :type delay: float
        :param delay: delay in seconds and then run fetcher
        :return: a generator that yields request id and encoded vector in a tuple, where the request id can be used to determine the order
        :rtype: Iterator[tuple(int, numpy.ndarray)]

        """
        time.sleep(delay)
        while self.pending_request:
            yield self._recv_ndarray()

    def fetch_all(self, sort=True, concat=False, parse_id_func=None, return_id=False):
        """ Fetch all encoded vectors from server, use it with `encode(blocking=False)`

        Use it `encode(texts, blocking=False)`. If there is no pending requests, it will return None.

        :type sort: bool
        :type concat: bool
        :param sort: sort results by their request ids. It should be True if you want to preserve the sending order
        :param concat: concatenate all results into one ndarray
        :return: encoded sentence/token-level embeddings in sending order
        :rtype: numpy.ndarray or list[list[float]]

        """
        if self.pending_request:
            tmp = list(self.fetch())

            # check for exception
            for t in tmp:
                if t.error_code == 1:
                    warnings.warn("Request with id: {}\nRaised an error from server with message:\n{}".format(t.id, t.error_message))

            if sort:
                if parse_id_func is None:
                    parse_id_func = lambda v: v.id
                tmp = sorted(tmp, key=parse_id_func)
            if return_id:
                tmp = [(v.id, v.embedding) for v in tmp]
            else:
                tmp = [v.embedding for v in tmp]
            if concat:
                if self.protocol == 'numpy':
                    tmp = np.concatenate(tmp, axis=0)
                elif self.protocol == 'obj':
                    tmp = [vv for v in tmp for vv in v]
            return tmp

    def encode_async(self, batch_generator, max_num_batch=None, delay=0.1, **kwargs):
        """ Async encode batches from a generator

        :param delay: delay in seconds and then run fetcher
        :param batch_generator: a generator that yields list[str] or list[list[str]] (for `is_tokenized=True`) every time
        :param max_num_batch: stop after encoding this number of batches
        :param `**kwargs`: the rest parameters please refer to `encode()`
        :return: a generator that yields encoded vectors in ndarray, where the request id can be used to determine the order
        :rtype: Iterator[tuple(int, numpy.ndarray)]

        """

        def run():
            cnt = 0
            for texts in batch_generator:
                self.encode(texts, blocking=False, **kwargs)
                cnt += 1
                if max_num_batch and cnt == max_num_batch:
                    break

        t = threading.Thread(target=run)
        t.start()
        return self.fetch(delay)

    @staticmethod
    def _check_length(texts, len_limit):
        # do a simple whitespace tokenizer
        return all(len(t.split()) <= len_limit for t in texts)

    @staticmethod
    def _print_dict(x, title=None):
        if title:
            print(title)
        for k, v in x.items():
            print('%30s\t=\t%-30s' % (k, v))

    def __enter__(self):
        print('begin', self.identity)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        print('end', self.identity, exc_type, exc_val, exc_tb)
        self.close()


class BCManager():
    def __init__(self, available_bc, retry=0, retry_gap=0.05):
        self.available_bc = available_bc
        self.bc = None
        self.retry = retry
        self.retry_gap = retry_gap

    def _enter_bc(self, retry=0, retry_gap=0.05):
        try:
            self.bc = self.available_bc.pop()
            return self.bc
        except Exception as e:
            if retry > 0:
                random_amount = 0.1*retry_gap*(np.random.random()*2-1) # prevent deadlock
                time.sleep(retry_gap + random_amount)   
                return self._enter_bc(retry=retry-1)
            else:
                raise e

    def __enter__(self):
        return self._enter_bc(retry=self.retry, retry_gap=self.retry_gap)

    def __exit__(self, *args):
        self.available_bc.append(self.bc)


class ConcurrentWKRClient(WKRClient):
    def __init__(self, max_concurrency=10, retry=0, retry_gap=0.05, **kwargs):
        """ A thread-safe client object connected to a TTSServer

        Create a WKRClient that connects to a TTSServer.
        Note, server must be ready at the moment you are calling this function.
        If you are not sure whether the server is ready, then please set `check_version=False` and `check_length=False`

        :type max_concurrency: int
        :param max_concurrency: the maximum number of concurrent connections allowed

        """
        try:
            from wkr_serving.client import WKRClient
        except ImportError:
            raise ImportError('WKRClient module is not available, it is required for serving HTTP requests.'
                              'Please use "pip install -U tts-serving-client" to install it.'
                              'If you do not want to use it as an HTTP server, '
                              'then remove "-http_port" from the command line.')

        self.available_bc = [WKRClient(**kwargs) for _ in range(max_concurrency)]
        self.max_concurrency = max_concurrency
        self.retry = retry
        self.retry_gap = retry_gap

    def close(self):
        for bc in self.available_bc:
            bc.close()

    def _concurrent(func):
        @wraps(func)
        def arg_wrapper(self, *args, **kwargs):
            try:
                with BCManager(self.available_bc, retry=self.retry, retry_gap=self.retry_gap) as bc:
                    f = getattr(bc, func.__name__)
                    r = f if isinstance(f, dict) else f(*args, **kwargs)
                return r
            except IndexError:
                raise RuntimeError('Too many concurrent connections!'
                                   'Try to increase the value of "max_concurrency", '
                                   'currently =%d' % self.max_concurrency)

        return arg_wrapper

    @_concurrent
    def encode(self, **kwargs):
        pass

    @property
    @_concurrent
    def server_status(self):
        pass

    @property
    @_concurrent
    def status(self):
        pass

    def fetch(self, **kwargs):
        raise NotImplementedError('Async encoding of "ConcurrentWKRClient" is not implemented yet')

    def fetch_all(self, **kwargs):
        raise NotImplementedError('Async encoding of "ConcurrentWKRClient" is not implemented yet')

    def encode_async(self, **kwargs):
        raise NotImplementedError('Async encoding of "ConcurrentWKRClient" is not implemented yet')
