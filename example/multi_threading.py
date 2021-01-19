import os
import time
import sys
import threading
import numpy as np

from wkr_serving.client import WKRClient

def build_input(url):
    # download image
    # crop image
    return [] # list face

def process_data(client, data):

    faces = build_input(data)

    for i, face in enumerate(faces):
        client.encode({
            'id': i,
            'face_img': face
        }, blocking=False)

    time.sleep(0.02)

    predicted = client.fetch_all()

    return predicted

def save_result(result):
    # save result
    pass

def predict(data_array):
    client = WKRClient(ip='0.0.0.0', port=8996, port_out=8998, check_version=False)
    for data in data_array:
        predicted = process_data(client, data)
        save_result(predicted)

def split_data(datas, split_num):
    total_length = len(datas)
    split_index = np.array(list(range(0, total_length, split_num)))
    splits = []
    for idx in range(split_num):
        split_idx = split_index + idx
        splits.append(datas[split_idx,...])
    return splits

if __name__ == '__main__':

    # set number of downloading thread
    thread_num = 12

    # load numpy data
    datas = np.array([]) # shape [n,...], n samples
    data_splited = split_data(datas, thread_num)


    database = {
        1: [],
        2: [],
    }

    for idx in range(thread_num):
        threading.Thread(target=predict, args=(database, idx)).start()

    for idx in range(thread_num):
        threading.Thread(target=predict, args=(database, idx)).start()

