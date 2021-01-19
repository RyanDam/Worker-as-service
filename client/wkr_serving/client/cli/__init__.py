def switch_remote_server():
    from wkr_serving.client import WKRDecentralizeCentral
    from wkr_serving.client.helper import get_run_args, get_switch_parser
    args = get_run_args(get_switch_parser)
    WKRDecentralizeCentral.switch_server(args)

def show_config():
    from wkr_serving.client import WKRDecentralizeCentral
    from wkr_serving.client.helper import get_run_args, get_status_parser
    args = get_run_args(get_status_parser)
    WKRDecentralizeCentral.show_config(args)

def terminate():
    from wkr_serving.client import WKRDecentralizeCentral
    from wkr_serving.client.helper import get_run_args, get_shutdown_parser
    args = get_run_args(get_shutdown_parser)
    WKRDecentralizeCentral.terminate(args)

def idle():
    from wkr_serving.client import WKRDecentralizeCentral
    from wkr_serving.client.helper import get_run_args, get_shutdown_parser
    args = get_run_args(get_shutdown_parser)
    WKRDecentralizeCentral.idle(args)

def restart_clients():
    from wkr_serving.client import WKRDecentralizeCentral
    from wkr_serving.client.helper import get_run_args, get_shutdown_parser
    args = get_run_args(get_shutdown_parser)
    WKRDecentralizeCentral.restart_clients(args)
