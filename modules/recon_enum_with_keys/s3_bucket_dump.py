#!/usr/bin/env python3
import boto3, argparse, os, time, json, sys, botocore
from botocore.exceptions import ClientError
from copy import deepcopy
from functools import partial
from pacu import util

module_info = {
    # Name of the module (should be the same as the filename)
    'name': 's3_bucket_dump',

    # Name and any other notes about the author
    'author': 'Spencer Gietzen of Rhino Security Labs',

    # One liner description of the module functionality. This shows up when a user searches for modules.
    'one_liner': 'Enumerate and dumps files from S3 buckets.',

    # Description about what the module does and how it works
    'description': 'This module scans the current account for AWS buckets and prints/stores as much data as it can about each one. With no arguments, this module will enumerate all buckets the account has access to, then prompt you to download all files in the bucket or not. Use --names-only or --dl-names to change that. The files will be downloaded to ./sessions/[current_session_name]/downloads/s3_dump/.',

    # A list of AWS services that the module utilizes during its execution
    'services': ['S3'],

    # For prerequisite modules, try and see if any existing modules return the data that is required for your module before writing that code yourself, that way, session data can stay separated and modular.
    'prerequisite_modules': [],

    # Module arguments to autocomplete when the user hits tab
    'arguments_to_autocomplete': ['--dl-all', '--names-only', '--dl-names'],
}

parser = argparse.ArgumentParser(add_help=False, description=module_info['description'])

parser.add_argument('--dl-all', required=False, action='store_true', help='If specified, automatically download all files from buckets that are allowed instead of asking for each one. WARNING: This could mean you could potentially be downloading terrabytes of data! It is suggested to user --names-only and then --dl-names to download specific files.')
parser.add_argument('--names-only', required=False, action='store_true', help='If specified, only pull the names of files in the buckets instead of downloading. This can help in cases where the whole bucket is a large amount of data and you only want to target specific files for download. This option will store the filenames in a .txt file in ./sessions/[current_session_name]/downloads/s3_dump/s3_bucket_dump_file_names.txt, one per line, formatted as "filename@bucketname". These can then be used with the "--dl-names" option.')
parser.add_argument('--dl-names', required=False, default=False, help='A path to a file that includes the only files to be downloaded, one per line. The format for these files must be "filename.ext@bucketname", which is what the --names-only argument outputs.')


def help():
    return [module_info, parser.format_help()]


def main(args, proxy_settings, database):
    session = util.get_active_session(database)

    ###### Don't modify these. They can be removed if you are not using the function.
    args = parser.parse_args(args)
    print = partial(util.print, session_name=session.name, database=database)
    input = partial(util.input, session_name=session.name, database=database)
    ######

    if (args.names_only is True and args.dl_names is True) or (args.names_only is True and args.dl_all is True) or (args.dl_names is True and args.dl_all is True):
        print('Only zero or one options of --dl-all, --names-only, and --dl-names may be specified. Exiting...')
        return
    client = boto3.client(
        's3',
        aws_access_key_id=session.access_key_id,
        aws_secret_access_key=session.secret_access_key,
        aws_session_token=session.session_token,
        config=botocore.config.Config(proxies={'https': 'socks5://127.0.0.1:8001', 'http': 'socks5://127.0.0.1:8001'}) if proxy_settings.target_agent is not None else None
    )
    s3 = boto3.resource(
        's3',
        aws_access_key_id=session.access_key_id,
        aws_secret_access_key=session.secret_access_key,
        aws_session_token=session.session_token,
        config=botocore.config.Config(proxies={'https': 'socks5://127.0.0.1:8001', 'http': 'socks5://127.0.0.1:8001'}) if proxy_settings.target_agent is not None else None
    )
    buckets = []
    names_and_buckets = None
    if args.dl_names is False:
        print('Finding existing buckets...')
        response = client.list_buckets()
        s3_data = deepcopy(session.S3)
        s3_data['Buckets'] = deepcopy(response['Buckets'])
        session.update(database, S3=s3_data)
        for bucket in response['Buckets']:
            buckets.append(bucket['Name'])
            print('  Found bucket "{}".'.format(bucket['Name']))
    else:
        print('Found --dl-names argument, skipping bucket enumeration.')
        with open(args.dl_names, 'r') as files_file:
            names_and_buckets = files_file.read().split('\n')
            for item in names_and_buckets:
                if '@' in item:
                    supplied_bucket = item.split('@')[1]
                    buckets.append(supplied_bucket)
            buckets = list(set(buckets)) # Delete duplicates
        print('Relevant buckets extracted from the supplied list include:\n{}\n'.format('\n'.join(buckets)))
    print('Starting scan process...')
    for bucket in buckets:
        print('  Bucket name: "{}"'.format(bucket))
        try:
            print('    Checking read permissions...'.format(bucket))
            response = client.list_objects_v2(
                Bucket=bucket,
                MaxKeys=10
            )
            if args.dl_all is False and args.names_only is False and args.dl_names is False:
                try_to_dl = input('      You have permission to read files in bucket {}, do you want to attempt to download all files in it? (y/n) '.format(bucket))
                if try_to_dl == 'n':
                    print('      Skipping to next bucket.')
                    continue
            elif args.names_only is True:
                try_to_dl = 'n'
            else:
                try_to_dl = 'y'
        except:
            try_to_dl = 'n'
            print('      You do not have permission to view files in bucket {}, skipping to next bucket.'.format(bucket))
            continue
        if try_to_dl == 'y':
            try:
                print('    Attempting to download a test file...'.format(bucket))
                first_obj_key = response['Contents'][0]['Key']
                i = 0
                while first_obj_key[-1] == '/':
                    i += 1
                    first_obj_key = response['Contents'][i]['Key']
                if not os.path.exists('tmp/{}'.format(os.path.dirname(first_obj_key))):
                    os.makedirs('tmp/{}'.format(os.path.dirname(first_obj_key)))
                s3.meta.client.download_file(bucket, first_obj_key, 'tmp/{}'.format(first_obj_key))
                file = open('tmp/{}'.format(first_obj_key), 'rb')
                test = file.read()
                file.close()
                print('      Test file has been downloaded to ./tmp and read successfully.')
            except Exception as e:
                print(e)
                print('      Test file has failed to be downloaded and read, skipping to next bucket.')
                continue
        s3_objects = []
        if args.dl_names is False:
            try:
                if not os.path.exists('sessions/{}/downloads/s3_dump/{}'.format(session.name, bucket)):
                    os.makedirs('sessions/{}/downloads/s3_dump/{}'.format(session.name, bucket))
                response = None
                continuation_token = False
                print('    Finding all files in the bucket...')
                while (response is None or 'NextContinuationToken' in response):
                    if continuation_token is False:
                        response = client.list_objects_v2(
                            Bucket=bucket,
                            MaxKeys=100
                        )
                    else:
                        response = client.list_objects_v2(
                            Bucket=bucket,
                            MaxKeys=100,
                            ContinuationToken=continuation_token
                        )
                    if 'NextContinuationToken' in response:
                        continuation_token = response['NextContinuationToken']
                    for s3_obj in response['Contents']:
                        if s3_obj['Key'][-1] == '/':
                            if not os.path.exists('sessions/{}/downloads/s3_dump/{}/{}'.format(session.name, bucket, s3_obj['Key'])):
                                os.makedirs('sessions/{}/downloads/s3_dump/{}/{}'.format(session.name, bucket, s3_obj['Key']))
                        else:
                            s3_objects.append(s3_obj['Key'])
                print('      Successfully collected all available file names.')
            except Exception as e:
                print(e)
                print('      Failed to collect all available files, skipping to the next bucket...')
                continue

            with open('sessions/{}/downloads/s3_dump/s3_bucket_dump_file_names.txt'.format(session.name), 'w+') as file_names_list:
                for file in s3_objects:
                    file_names_list.write('{}@{}\n'.format(file, bucket))
                file_names_list.close()
            print('    Saved found file names to ./sessions/{}/downloads/s3_dump/s3_bucket_dump_file_names.txt.'.format(session.name))
        else:
            print('    File names were supplied, skipping file name enumeration.')
        if args.names_only is False:
            print('    Starting to download files...')
            if args.dl_names is not False:
                for file in names_and_buckets:
                    if '@{}'.format(bucket) in file:
                        s3_objects.append(file.split('@{}'.format(bucket))[0])
            failed_dl = 0
            cont = 'y'
            for key in s3_objects:
                if failed_dl > 4 and cont == 'y':
                    cont = input('    There have been 5 failed downloads in a row, do you want to continue and ignore this message for the current bucket (y) or move onto the next bucket (n)? ')
                if cont == 'y':
                    try:
                        print('      Downloading file {}...'.format(key))

                        nested_key_directory_path, file_name = os.path.split(key)
                        bucket_directory_path = 'sessions/{}/downloads/s3_dump/{}'.format(session.name, bucket)
                        key_directory_path = os.path.join(bucket_directory_path, nested_key_directory_path)

                        if not os.path.exists(key_directory_path):
                            os.makedirs(key_directory_path)

                        key_file_path = os.path.join(key_directory_path, file_name)
                        s3.meta.client.download_file(bucket, key, key_file_path)

                        print('        Successful.')
                        failed_dl = 0

                    except Exception as e:
                        print(e)
                        print('        Failed to download, moving onto next file.')
                        failed_dl += 1

    print('All buckets have been analyzed.')
    print('\n{} completed.'.format(os.path.basename(__file__)))
    return
