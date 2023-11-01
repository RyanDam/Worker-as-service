# Worker as service

Worker-as-service is a high-efficient deployment framework for general computing:
- Low latency & high throughput messaging pipeline
- Micro-batching 
- Ease of use, event data science can deploy a service with low maintanance effort
- Decentralize deployment
- Native python support, pre-defined protobuf (gRPC likes) is needed
- Resful API support
- Statistic support out-of-the-box

## Architecture

![overall architecture](images/WKR_scheme.jpg)

## Installation

- step 1: clone this project to local machine

- step 2: navigate to `worker-as-service/server`:
```
pip install -e .
```

- step 3: navigate to `worker-as-service/client`:
```
pip install -e .
```

- step 4: Checkout example in `worker-as-service/example` for custom server:

## Credit

- [Clip-as-service](https://github.com/jina-ai/clip-as-service) (formerly known as Bert-as-service): Worker-as-service is heavily based on Bert-as-service.
- [PyZMQ](https://github.com/zeromq/pyzmq): for effience transport layer.