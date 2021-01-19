import os

from multiprocessing import Process, Event
from termcolor import colored
from .helper import set_logger

import time
from PIL import Image
import urllib.request as urllib_request
from io import BytesIO
import json

class MaxFileSizeExeeded(Exception):
    pass

class NotSupportedInputFile(Exception):
    pass

def download_img_file(url, retry=50, retry_gap=0.1, proxy=None):
#     export http_proxy=http://10.30.80.254:81
#     export https_proxy=http://10.30.80.254:81
    if proxy is not None:
        proxies = {'http': proxy, 'https': proxy}
    else:
        proxies = {}

    try:
        proxy_handler = urllib_request.ProxyHandler(proxies)
        opener = urllib_request.build_opener(proxy_handler)
        img = Image.open(BytesIO(opener.open(url).read())).convert('RGB')
        return img
    except Exception as e:
        print(e)
        if retry > 0:
            time.sleep(retry_gap)   
            return download_img_file(url, retry=retry-1)
        else:
            raise e

def check_request_size(request, max_size = 5 * 1024 * 1024):
    if request.content_length > max_size:
        raise MaxFileSizeExeeded("Input file size too large, limit is {:0.2f}MB".format(max_size/(1024**2)))

def convert_bytes_to_pil_image(img_bytes):
    try:
        img = Image.open(BytesIO(img_bytes)).convert("RGB")
        return img
    except:
        raise NotSupportedInputFile("Wrong input file type, only accept jpg or png image")

class BertHTTPProxy(Process):

    def __init__(self, args):
        super().__init__()
        self.args = args
        self.is_ready = Event()
        self.logger = set_logger(colored('PROXY', 'red'), logger_dir=args.log_dir, verbose=args.verbose)

    def create_flask_app(self, args):
        try:
            from flask import Flask, request, jsonify, render_template, send_from_directory
            from flask_compress import Compress
            from flask_cors import CORS
            from flask_json import FlaskJSON, as_json, JsonError
            
            from wkr_serving.client import ConcurrentWKRClient
        except ImportError:
            raise ImportError('WKRClient or Flask or its dependencies are not fully installed, '
                              'they are required for serving HTTP requests.'
                              'Please use "pip install -U bert-serving-server[http]" to install it.')

        # support up to 10 concurrent HTTP requests
        bc = ConcurrentWKRClient(max_concurrency=self.args.http_max_connect,
                                  port=self.args.port, port_out=self.args.port_out,
                                  protocol='obj', ignore_all_checks=True)

        logger = set_logger(colored('PROXY', 'red'), logger_dir=args.log_dir, verbose=args.verbose)

        if os.path.isdir(self.args.http_stat_dashboard):
            app = Flask(__name__, template_folder=self.args.http_stat_dashboard, static_folder=self.args.http_stat_dashboard)
            @app.route('/stat', methods=['GET'])
            def get_server_status_ui():
                return render_template('index.html', tt_text='{{tt.text}}', tt_value='{{tt.value}}')
            @app.route('/static/<filename>', methods=['GET'])
            def get_static_file(filename):
                return send_from_directory(self.args.http_stat_dashboard, filename)
        else:
            app = Flask(__name__)

        @app.route('/status/server', methods=['GET'])
        # @as_json
        def get_server_status():
            return jsonify(bc.server_status)

        @app.route('/status/client', methods=['GET'])
        # @as_json
        def get_client_status():
            return jsonify(bc.status)

        @app.route('/tmp/<filename>', methods=['GET'])
        def get_temp_file(filename):
            return send_from_directory("/tmp/", filename)

        @app.route('/encode_img_bytes', methods=['POST'])
        # @as_json
        def encode_query_img_bytes():
            try:
                logger.info('new request from %s' % request.remote_addr)
                if 'img_bytes' in request.files:
                    img_bytes = request.files['img_bytes'].read()
                    img = Image.open(BytesIO(img_bytes))
                    final_res = bc.encode(img)
                    return jsonify({
                        "error_code": 0,
                        "error_message": "Success.",
                        "data": final_res
                    })
                else:
                    raise Exception('wrong request parameter, must contain "img_bytes"')
            except Exception as e:
                logger.error('error when handling HTTP request', exc_info=True)
                return jsonify({
                        "error_code": 1,
                        "error_message": str(e),
                        "data": {}
                    })

        @app.route('/v1/encode_img_bytes', methods=['POST'])
        def v1_encode_query_img_bytes():
            try:
                logger.info('new request from %s' % request.remote_addr)
                check_request_size(request)
                if 'img_bytes' in request.files:
                    img_bytes = request.files['img_bytes'].read()
                    img = convert_bytes_to_pil_image(img_bytes)
                    final_res = bc.encode(img)
                    return jsonify({
                        "error_code": 0,
                        "error_message": "Successful.",
                        "data": final_res
                    }), 200
                else:
                    return jsonify({
                        "error_code": 400,
                        "error_message": "Wrong request parameter, must contain \"img_bytes\"",
                        "data": {}
                    }), 400
            except NotSupportedInputFile as e:
                return jsonify({
                    "error_code": 400,
                    "error_message": str(e),
                    "data": {}
                }), 400
            except MaxFileSizeExeeded as e:
                return jsonify({
                    "error_code": 413,
                    "error_message": str(e),
                    "data": {}
                }), 413
            except Exception as e:
                logger.error('error when handling HTTP request', exc_info=True)
                return jsonify({
                    "error_code": 500,
                    "error_message": "Internal server error",
                    "data": {}
                }), 500

        @app.route('/encode_img_url', methods=['POST'])
        # @as_json
        def encode_query_img_url():
            data = request.form if request.form else request.json
            try:
                logger.info('new request from %s' % request.remote_addr)
                if 'img_url' in data:
                    img_url = data['img_url']
                    proxy = None
                    if 'proxy' in data:
                        proxy = data['proxy']
                    img = download_img_file(img_url, proxy=proxy, retry=1)
                    final_res = bc.encode(img)
                    return jsonify({
                        "error_code": 0,
                        "error_message": "Success.",
                        "data": final_res
                    })
                else:
                    raise Exception('wrong request parameter, must contain "img_url"')
            except Exception as e:
                logger.error('error when handling HTTP request', exc_info=True)
                return jsonify({
                        "error_code": 1,
                        "error_message": str(e),
                        "data": {}
                    })

        @app.route('/encode_json', methods=['POST'])
        def encode_query_json():
            # curl -H "Content-Type: application/json" \
            # -X POST \
            # -d '{"data1":"data1","data2":"data2"}' \
            # http://localhost:3000/encode_json
            try:
                # target_json = dict(request.json)
                target_json = json.loads(request.data)
                final_res = bc.encode(target_json)
                return jsonify({
                    "error_code": 0,
                    "error_message": "Success.",
                    "data": final_res
                })
            except Exception as e:
                logger.error('error when handling HTTP request', exc_info=True)
                return jsonify({
                        "error_code": 1,
                        "error_message": str(e),
                        "data": {}
                    })

        @app.route('/encode', methods=['POST'])
        # @as_json
        def encode_query():
            data = request.form if request.form else request.json
            try:
                logger.info('new request from %s' % request.remote_addr)
                if 'img_url' in data:
                    img_url = data['img_url']
                    final_res = bc.encode(img_url)
                    return jsonify({
                        "error_code": 0,
                        "error_message": "Success.",
                        "data": final_res
                    })
                else:
                    raise Exception('wrong request parameter, must contain "img_url"')

            except Exception as e:
                logger.error('error when handling HTTP request', exc_info=True)
                return jsonify({
                        "error_code": 1,
                        "error_message": str(e),
                        "data": {}
                    })

        CORS(app, origins=self.args.cors)
        FlaskJSON(app)
        Compress().init_app(app)

        return app

    def close(self):
        self.logger.info('shutting down...')
        self.is_ready.clear()
        self.terminate()
        self.join()
        self.logger.info('terminated!')

    def run(self):
        app = self.create_flask_app(self.args)
        self.is_ready.set()
        app.run(port=self.args.http_port, threaded=True, host='0.0.0.0', debug=False)
