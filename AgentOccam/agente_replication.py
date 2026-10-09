import argparse
import asyncio
from Agent_E.test.tests_processor import run_tests

if __name__ == "__main__":
    # Create the parser
    parser = argparse.ArgumentParser(description='Run test suite for specified range of test tasks.')

    # Add arguments
    parser.add_argument('-s', '--take_screenshots', type=bool, default=False,
                        help='Take screenshots after every operation performed (default: False)')
    parser.add_argument('-wait', '--wait_time_non_headless', type=int, default=5,
                        help='Time to wait between test tasks when running in non-headless mode (default: 10 seconds)')
    parser.add_argument("-ids", "--task_ids", type=str, nargs='+', help="List of task IDs to execute")
    parser.add_argument('-dir', '--logdir', type=str, default="../AgentOccam-Trajectories",
                        help='Logdir.')
    parser.add_argument('-log', '--logname', type=str, default="Agent-E",
                        help='Logname.')
    parser.add_argument('-id', '--test_results_id', type=str, default="",
                        help='A unique identifier for the test results. If not provided, a timestamp is used.')
    parser.add_argument('-config', '--relative_task_dir', type=str, default="webvoyager",
                        help='Path to the test configuration file.')

    # Parse the command line arguments
    args = parser.parse_args()

    # Run the main function with the provided or default arguments, not passing browser_manager or AutoGenWrapper will cause the test processor to create new instances of them
    asyncio.run(run_tests(None, None, args.task_ids, logdir=args.logdir, logname=args.logname, relative_task_dir=args.relative_task_dir,
                          take_screenshots=args.take_screenshots, wait_time_non_headless=args.wait_time_non_headless))
