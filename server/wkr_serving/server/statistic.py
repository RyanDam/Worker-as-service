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

class ServerStatistic:
    def __init__(self, sample_limit=1000, interval_seconds=3, secondary_sample_limit=1000):
        self._hist_client = defaultdict(int)
        self._client_last_active_time = defaultdict(float)
        self._num_data_req = 0
        self._num_sys_req = 0
        self._num_except_req = 0
        self._num_total_seq = 0
        self._last_req_time = time.time()
        self._last_two_req_interval = []
        self._last_rps_total = []
        self._last_rps_time = time.time()
        self._num_last_two_req = sample_limit
        self._rps_interval = interval_seconds
        self._ignored_first = False

        self._other_statistic = defaultdict(list)
        self._other_statistic_limit = secondary_sample_limit

    def update(self, request, ignore_first=False):

        if ignore_first == False and self._ignored_first == False:
            self._ignored_first = True
        else:
            client, msg, req_id, msg_len = request
            self._hist_client[client] += 1
            if ServerCmd.is_valid(msg):
                if msg == ServerCmd.exception:
                    self._num_except_req += 1
                else:
                    self._num_sys_req += 1
                # do not count for system request, as they are mainly for heartbeats
            else:
                self._num_total_seq += 1
                self._num_data_req += 1
                tmp = time.time()

                if tmp-self._last_rps_time > self._rps_interval:
                    self._last_rps_total.append(self._num_total_seq)
                    self._last_rps_time = tmp
                    if len(self._last_rps_total) > self._num_last_two_req:
                        self._last_rps_total.pop(0)

                self._client_last_active_time[client] = tmp
                self._last_two_req_interval.append(tmp - self._last_req_time)
                if len(self._last_two_req_interval) > self._num_last_two_req:
                    self._last_two_req_interval.pop(0)

                self._last_req_time = tmp

    def update_key(self, key, value):
        self._other_statistic[key].append(float(value))
        if len(self._other_statistic[key]) > self._other_statistic_limit:
            self._other_statistic[key].pop(0)

    @property
    def other_statistic_stat(self):
        result = {}
        for key, values in self._other_statistic.items():
            stat_dict = self.get_min_max_avg2('stat', values)
            result[key] = stat_dict
        return result

    @property
    def value(self):

        def get_num_active_client(interval=180):
            # we count a client active when its last request is within 3 min.
            now = time.perf_counter()
            return sum(1 for v in self._client_last_active_time.values() if (now - v) < interval)

        # rps = np.array(self._last_rps_total)
        # rps = (rps[1:]-rps[:-1])/self._rps_interval
        # rps = rps[rps>0]
        rps = self.get_request_per_second()

        parts = [{
            'num_data_request': self._num_data_req,
            'num_total_seq': self._num_total_seq,
            'num_sys_request': self._num_sys_req,
            'num_exception': self._num_except_req,
            'num_total_request': self._num_data_req + self._num_sys_req,
            'num_total_client': len(self._hist_client),
            'num_active_client': get_num_active_client(),
            'others': self.other_statistic_stat},
            self.get_min_max_avg('request_per_client', self._hist_client.values()),
            self.get_min_max_avg2('last_two_interval', self._last_two_req_interval),
            self.get_min_max_avg2('request_per_second', rps),
        ]

        return {k: v for d in parts for k, v in d.items()}

    def get_request_per_second(self):
        rps = np.array(self._last_rps_total)
        rps = (rps[1:]-rps[:-1])/self._rps_interval
        rps = rps[rps>0]
        return rps

    def get_min_max_avg(self, name, stat):
        if len(stat) > 0:
            return {
                'avg_%s' % name: sum(stat)/len(stat),
                'min_%s' % name: min(stat),
                'max_%s' % name: max(stat),
                'num_min_%s' % name: sum(v == min(stat) for v in stat),
                'num_max_%s' % name: sum(v == max(stat) for v in stat),
            }
        else:
            return {}

    def get_min_max_avg2(self, name, stat):
        if len(stat) > 0:
            return {
                'avg_%s' % name: np.mean(stat),
                'min_%s' % name: np.min(stat),
                'max_%s' % name: np.max(stat),
                'std_%s' % name: np.std(stat),
                'med_%s' % name: np.median(stat),
            }
        else:
            return {}