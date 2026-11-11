"""Run with python -m forgemind.task_cli. No daemon starts automatically."""
import argparse
import json
from pathlib import Path
from .config import app_data_dir
from .task_queue import TaskQueue
from .task_tools import run_one


def main():
    parser=argparse.ArgumentParser(description='Doxa local task queue')
    parser.add_argument('--data-dir',type=Path)
    commands=parser.add_subparsers(dest='command',required=True)
    add=commands.add_parser('calculate');add.add_argument('expression')
    commands.add_parser('run-once');commands.add_parser('list')
    for name in ('retry','cancel'):
        command=commands.add_parser(name);command.add_argument('id')
    args=parser.parse_args()
    queue=TaskQueue((args.data_dir if args.data_dir is not None else app_data_dir())/'task-queue.sqlite3')
    try:
        if args.command=='calculate':
            result={'queued':queue.submit('calculate',{'expression':args.expression})}
        elif args.command=='run-once':
            result={'processed':run_one(queue)}
        elif args.command=='list':
            result=queue.recent()
        else:
            getattr(queue,args.command)(args.id);result={'id':args.id,'action':args.command}
    except ValueError as exc:
        parser.exit(2,str(exc)+'\n')
    print(json.dumps(result,indent=2))


if __name__=='__main__':
    main()
