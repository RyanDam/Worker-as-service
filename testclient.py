import time
import numpy as np
import json
import pickle
from collections import defaultdict
import matplotlib.pyplot as plt
from wkr_serving.client import WKRClient

bc = WKRClient(ip='10.40.34.15', port=8770, port_out=8772, check_version=False, protocol='obj')

input = np.zeros((300,300))
bc.encode(input).shape

def kb_size(obj):
    return len(pickle.dumps(obj))/1024

def print_kb_size(obj):
    print("{:.2f} (kB)".format(kb_size(obj)))
    
def atime_cal(arr):
    return np.mean(arr)*1000
    
def print_time(arr):
    print("{:.2f} (ms)".format(atime_cal(arr)))

def bench(input, paralell=10, exp=100):
    obj_size = kb_size(input)
    def a(input, num=1):
        start = time.time()
        for _ in range(num):
            bc.encode(input, blocking=False)
        bc.fetch_all()
        return (time.time()-start)/num
    bb = [a(input, num=paralell) for _ in range(exp)]
    atim = atime_cal(bb)
    return obj_size, atim

objs = [
    {"content": "tôi là bê tô", "matrix": np.zeros((640,640,3)).astype(np.uint8)},
    {"content": "tôi là bê tô", "matrix": np.zeros((300,300,3)).astype(np.uint8)},
    {"content": "tôi là bê tô", "matrix": np.zeros((224,224,3)).astype(np.uint8)},
    {"content": "tôi là bê tô", "matrix": np.zeros((112,112,3)).astype(np.uint8)},
    {"content": "tôi là bê tô", "matrix": np.arange(25).reshape(5,5).astype(np.float32)}
]

records = defaultdict(lambda: defaultdict(float))

for obj in objs:
    for par in [1,2,4,8,16,32,64,128]:
        size, tim = bench(obj, paralell=par)
        records[size][par] = tim

with open('records16.bin', 'wb') as f:
    pickle.dump(dict(records), f)