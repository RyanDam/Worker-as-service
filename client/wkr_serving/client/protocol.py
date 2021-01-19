import os, sys
import zlib, pickle
import numpy as np
import zmq
from zmq.utils import jsonapi

__all__ = ['ServerCmd', 'ProcessingError', 
           'send_to_next', 'recv_from_prev',
           'to_bytes', 'to_str', 
           'send_object', 'recv_object', 'send_ndarray', 'decode_ndarray', 'decode_object', 'send_to_next_raw']

class ServerCmd:
    terminate = b'TERMINATION'
    idle_mode = b'IDLE'
    restart_client = b'RESTART_CLIENT'
    show_config = b'SHOW_CONFIG'
    switch_server = b'SWITCH'
    exception = b'EXCEPTION'

    @staticmethod
    def is_valid(cmd):
        return any(not k.startswith('__') and v == cmd for k, v in vars(ServerCmd).items())

class ProcessingError(Exception):
    "Raised when eception happend on server side"
    def __init__(self, msg, client_id, req_id):
        super(ProcessingError, self).__init__(msg)
        self.client_id = client_id
        self.req_id = req_id
        self.raw_msg = msg

def send_to_next(protocol, client, job_id, msg, dst, flags=0):
    assert protocol in ['obj', 'numpy'], "{} is an invalid transfer protocol, must be 'obj' or 'numpy'".format(protocol)
    
    if protocol == 'obj':
        send_object(dst, client, job_id, msg, flags=flags)
    else:
        send_ndarray(dst, client, job_id, msg, flags=flags)

def recv_from_prev(protocol, src):
    assert protocol in ['obj', 'numpy'], "{} is an invalid transfer protocol, must be 'obj' or 'numpy'".format(protocol)

    if protocol == 'obj':
        client, req_id, msg, msg_info = recv_object(src)
    else:
        client, req_id, msg, msg_info = recv_ndarray(src)

    return client, req_id, msg, msg_info

def send_to_next_raw(client, req_id, msg, msg_info, dst, flags=0, copy=True, track=False):
    dst.send_multipart([to_bytes(client), to_bytes(req_id), msg, msg_info], flags, copy=copy, track=track)

def send_ndarray(dst, client, job_id, array, flags=0, copy=True, track=False):
    md = dict(dtype=str(array.dtype), shape=array.shape)
    msg_info = jsonapi.dumps(md)
    send_to_next_raw(client, job_id, array, msg_info, dst, flags=flags, copy=copy, track=track )

def recv_ndarray(src):
    msg = src.recv_multipart()
    client, req_id, msg, msg_info = msg
    if msg_info == ServerCmd.exception:
        raise ProcessingError(to_str(msg), to_str(client), to_str(req_id))
    arr_info, arr_val = jsonapi.loads(msg_info), msg
    array = decode_ndarray(arr_val, arr_info)
    return to_str(client), to_str(req_id), array, arr_info

def decode_ndarray(buffer, info):
    return np.frombuffer(memoryview(buffer), dtype=info['dtype']).reshape(info['shape'])

def send_object(dst, client, job_id, obj, flags=0, copy=True, track=False, protocol=-1, need_compress=0):
    if need_compress == 1:
        p = pickle.dumps(obj, protocol)
        z = zlib.compress(p)
    else:
        z = pickle.dumps(obj, protocol)
    obj_info = jsonapi.dumps(dict(protocol=protocol, compress=need_compress))
    send_to_next_raw(client, job_id, z, obj_info, dst, flags=flags, copy=copy, track=track )

def recv_object(src):
    msg = src.recv_multipart()
    client, req_id, msg, msg_info = msg
    if msg_info == ServerCmd.exception:
        raise ProcessingError(to_str(msg), to_str(client), to_str(req_id))
    obj_info, obj_buffer = jsonapi.loads(msg_info), msg
    obj = decode_object(obj_buffer, obj_info)
    return to_str(client), to_str(req_id), obj, obj_info

def decode_object(buffer, info):
    pickle_protocol = info['protocol']
    need_decompress = info['compress']
    if need_decompress == 1:
        obj_decompressed = zlib.decompress(buffer)
        obj = pickle.loads(obj_decompressed)
    else:
        obj = pickle.loads(buffer)
    return obj

def to_bytes(bytes_or_str):
    if isinstance(bytes_or_str, str):
        value = bytes_or_str.encode() # uses 'utf-8' for encoding
    else:
        value = bytes_or_str
    return value # Instance of bytes

def to_str(bytes_or_str):
    if isinstance(bytes_or_str, bytes):
        value = bytes_or_str.decode() # uses 'utf-8' for encoding
    else:
        value = bytes_or_str
    return value # Instance of str