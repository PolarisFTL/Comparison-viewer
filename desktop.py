"""Source and frozen GUI entry point."""
import sys
from platform_support import pick_directory_main, notify_error, choose_workspace

if __name__ == '__main__':
    if '--pick-directory' in sys.argv:
        position=sys.argv.index('--pick-directory')
        output=sys.argv[sys.argv.index('--picker-output')+1] if '--picker-output' in sys.argv else None
        sys.exit(pick_directory_main(sys.argv[position+1] if len(sys.argv)>position+1 else '',output))
    try:
        import server
        sys.exit(server.main())
    except PermissionError as error:
        if not any(arg=='--workspace' or arg.startswith('--workspace=') for arg in sys.argv[1:]):
            try:
                selected=choose_workspace()
                if selected:sys.exit(server.main(sys.argv[1:]+['--workspace',str(selected)]))
            except Exception as retry_error:
                notify_error(str(retry_error))
        else:notify_error('所选工作区不可写：'+str(error))
        sys.exit(1)
    except Exception as error:
        notify_error(str(error))
        sys.exit(1)
