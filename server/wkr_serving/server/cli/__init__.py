def main():
    from wkr_serving.server import WKRServer, WKRHardWorker
    from wkr_serving.server.helper import get_run_args, get_cli_start_parser, import_class_from_local
    args = get_run_args(get_cli_start_parser)
    try:
        skeleton_class = import_class_from_local(args.worker_class)
    except Exception as e:
        raise Exception("{}\nCAN'T IMPORT worker_class: {}".format(e, args.worker_class))
    else:
        if not issubclass(skeleton_class, WKRHardWorker):
            raise AssertionError('{} must inherit from class "wkr_serving.server.WKRHardWorker"'.format(worker_class.__name__))
        with WKRServer(args, hardprocesser=skeleton_class) as server:
            server.join()

def terminate():
    from wkr_serving.server import WKRServer
    from wkr_serving.server.helper import get_run_args, get_shutdown_parser
    args = get_run_args(get_shutdown_parser)
    WKRServer.shutdown(args)

def main_make():
    import os
    from wkr_serving.server.helper import get_run_args, get_cli_start_parser, import_class_from_local

    script_param = ['name']
    script_param_des = ['Name of this service']
    def script_parser():
        parser = get_cli_start_parser()
        for param, description in zip(script_param, script_param_des):
            parser.add_argument(f'-{param}', type=str, help=description, required=True)
        return parser

    args = get_run_args(script_parser, printed=False)
    opts = []
    for k, v in sorted(vars(args).items()):
        if str(v).lower() == 'none':
            continue
        if k in ["verbose", 'cpu', 'cors', 'worker_class', *script_param]:
            continue
        if k == 'device_map':
            v = ' '.join([str(d) for d in v])
        opts.append(f"-{k} {v} \\\n")
    opts = ''.join(opts)
    opts = opts[:-3]
    opts = f'wkr-serving-start \\\n{opts} \\\n{args.worker_class}'

    service_name = args.name
    log_file = 'logs/std.log'
    daemon = ''

    print('''DAEMON_PATH="'''+os.getcwd()+'''"
LOG_FILE=$DAEMON_PATH/'''+log_file+'''

DAEMON="'''+daemon+'''"
DAEMONOPTS="'''+opts+'''"

NAME='''+service_name+'''
SERVICE='''+service_name+'''
DESC="'''+service_name+'''"
PIDFILE=$DAEMON_PATH/$SERVICE.pid

case "$1" in
start)
	printf "%-50s" "Starting $NAME..."
	cd $DAEMON_PATH
	#PID=`$DAEMON $DAEMONOPTS > /dev/null 2>&1 & echo $!`
	$DAEMON $DAEMONOPTS > $LOG_FILE 2>&1 &
	PID=`echo -n $!`
	#echo "Saving PID" $PID " to " $PIDFILE
        if [ -z $PID ]; then
            printf "%s\n" "Fail"
        else
            echo $PID > $PIDFILE
            printf "%s\n" "Ok"
        fi
;;
stop)
    printf "%-50s" "Stopping $NAME"
    wkr-serving-terminate -port '''+str(args.port)+'''
    printf "%s\n" "Ok"
;;
stopf)
    ps aux | grep -w "'''+opts.replace("\\\n", "")+'''" | grep -v grep  | awk '{ print $2 }' | xargs -i -t kill -9 {}
    printf "%-50s" "Stopping $NAME"
        PID=`cat $PIDFILE`
        cd $DAEMON_PATH
    if [ -f $PIDFILE ]; then
        kill -HUP $PID
        printf "%s\n" "Ok"
        rm -f $PIDFILE
    else
        printf "%s\n" "pidfile not found"
    fi
;;
restart)
  	$0 stop
  	$0 start
;;

*)
        echo "Usage: $0 {start|stop|stopf|restart}"
        exit 1
esac''')