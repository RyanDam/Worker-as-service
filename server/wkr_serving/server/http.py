import os
from typing import Optional
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
        self.logger = set_logger(colored('PROXY', 'red'), logger_dir=args.log_dir, logger_name=args.log_name, verbose=args.verbose)

    def create_app(self, args):
        try:
            from fastapi import FastAPI
            from fastapi import File, Form, UploadFile, Header, Depends, Request, status
            from fastapi.staticfiles import StaticFiles
            from fastapi.exceptions import RequestValidationError
            from fastapi.responses import JSONResponse
            from fastapi.encoders import jsonable_encoder
            from pydantic import BaseModel

            from wkr_serving.client import ConcurrentWKRClient
        except ImportError:
            raise ImportError('WKRClient or FastAPI or its dependencies are not fully installed, '
                              'they are required for serving HTTP requests.'
                              'Please use "pip install -U fastapi uvicorn[standard] python-multipart aiofiles" to install it.')

        # support up to 10 concurrent HTTP requests
        bc = ConcurrentWKRClient(max_concurrency=self.args.http_max_connect,
                                  port=self.args.port, port_out=self.args.port_out,
                                  protocol='obj', ignore_all_checks=True)

        logger = set_logger(colored('PROXY', 'red'), logger_dir=args.log_dir, logger_name=args.log_name, verbose=args.verbose)

        if os.path.isdir(self.args.http_stat_dashboard):
            raise Exception("Stat page is not supported")
        else:
            app = FastAPI()

        @app.get('/status/server')
        async def get_server_status():
            try:
                status = bc.server_status
            except Exception as e:
                status = {}
            return status

        @app.get('/status/client')
        async def get_client_status():
            try:
                status = bc.status
            except Exception as e:
                status = {}
            return status

        app.mount('/tmp/', StaticFiles(directory="/tmp/"), name="temp")

        async def valid_content_length(content_length: int = Header(..., lt=5_242_880)):
            return content_length

        @app.post('/encode_img_bytes', dependencies=[Depends(valid_content_length)])
        async def encode_query_img_bytes(
            img_bytes: bytes = File(...)
        ):
            try:
                img = Image.open(BytesIO(img_bytes))
                final_res = bc.encode(img)
                return {
                    "error_code": 0,
                    "error_message": "Success.",
                    "data": final_res
                }
            except Exception as e:
                logger.error('error when handling HTTP request', exc_info=True)
                return {
                        "error_code": 1,
                        "error_message": str(e),
                        "data": {}
                    }

        @app.post('/v1/encode_img_bytes', dependencies=[Depends(valid_content_length)])
        async def v1_encode_query_img_bytes(
            img_bytes: bytes = File(...)
        ):
            try:
                # logger.info('new request from %s' % request.remote_addr)
                img = convert_bytes_to_pil_image(img_bytes)
                final_res = bc.encode(img)
                return {
                    "error_code": 0,
                    "error_message": "Successful.",
                    "data": final_res
                }
            except NotSupportedInputFile as e:
                return {
                    "error_code": 400,
                    "error_message": str(e),
                    "data": {}
                }
            except MaxFileSizeExeeded as e:
                return {
                    "error_code": 413,
                    "error_message": str(e),
                    "data": {}
                }
            except Exception as e:
                logger.error('error when handling HTTP request', exc_info=True)
                return {
                    "error_code": 500,
                    "error_message": "Internal server error",
                    "data": {}
                }

        class EncodeImageParams(BaseModel):
            img_url: str
            proxy: Optional[str] = None

        @app.post('/encode_img_url')
        def encode_query_img_url(
            item: EncodeImageParams
        ):
            try:
                # logger.info('new request from %s' % request.remote_addr)
                # img = download_img_file(item.img_url, proxy=item.proxy, retry=1)
                final_res = bc.encode(item.img_url)
                return {
                    "error_code": 0,
                    "error_message": "Success.",
                    "data": final_res
                }
            except Exception as e:
                logger.error('error when handling HTTP request', exc_info=True)
                return {
                        "error_code": 1,
                        "error_message": str(e),
                        "data": {}
                    }

        @app.post('/encode_json')
        async def encode_query_json(
            target_json: dict
        ):
            # curl -H "Content-Type: application/json" \
            # -X POST \
            # -d '{"data1":"data1","data2":"data2"}' \
            # http://localhost:3000/encode_json
            try:
                final_res = bc.encode(target_json)
                return {
                    "error_code": 0,
                    "error_message": "Success.",
                    "data": final_res
                }
            except Exception as e:
                logger.error('error when handling HTTP request', exc_info=True)
                return {
                        "error_code": 1,
                        "error_message": str(e),
                        "data": {}
                    }

        @app.middleware("http")
        async def add_process_time_header(request: Request, call_next):
            # print(vars(request))
            # {'scope': {'type': 'http', 'asgi': {'version': '3.0', 'spec_version': '2.1'}, 'http_version': '1.1', 'server': ('127.0.0.1', 9000), 'client': ('127.0.0.1', 38868), 'scheme': 'http', 'method': 'POST', 'root_path': '', 'path': '/encode_json', 'raw_path': b'/encode_json', 'query_string': b'', 'headers': [(b'user-agent', b'curl/7.29.0'), (b'host', b'localhost:9000'), (b'accept', b'*/*'), (b'content-type', b'application/json'), (b'content-length', b'33')], 'app': <fastapi.applications.FastAPI object at 0x7f8d8d0daf60>}, '_receive': <bound method RequestResponseCycle.receive of <uvicorn.protocols.http.httptools_impl.RequestResponseCycle object at 0x7f8d83120c88>>, '_send': <function empty_send at 0x7f8d83afa840>, '_stream_consumed': False, '_is_disconnected': False}
            logger.info(f'new request to api: {request.scope["path"]} from {request.scope["client"][0]}')
            start_time = time.time()
            response = await call_next(request)
            process_time = time.time() - start_time
            response.headers["X-Process-Time"] = str(process_time)
            return response

        @app.exception_handler(RequestValidationError)
        async def validation_exception_handler(request: Request, exc: RequestValidationError):
            return JSONResponse(
                status_code=200,  
                content=jsonable_encoder({
                    "error_code": 400,
                    "error_message": "Wrong request parameter",
                    "data": {}
                })
            )

        if self.args.http_api_appender != None:
            self.args.http_api_appender(app, bc)

        return app
        
    def close(self):
        self.logger.info('shutting down...')
        self.is_ready.clear()
        self.terminate()
        self.join()
        self.logger.info('terminated!')

    def run(self):
        import uvicorn
        app = self.create_app(self.args)
        self.is_ready.set()
        # app.run(port=self.args.http_port, threaded=True, host='0.0.0.0', debug=False)
        uvicorn.run(app, host="0.0.0.0", port=self.args.http_port, log_level="info", loop="asyncio")
