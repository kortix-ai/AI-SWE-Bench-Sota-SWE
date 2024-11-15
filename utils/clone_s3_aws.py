import boto3
import botocore

s3 = boto3.client('s3', config=botocore.client.Config(signature_version=botocore.UNSIGNED))
s3.download_file('swe-bench-experiments', 'verified/20241029_OpenHands-CodeAct-2.1-sonnet-20241022/trajs', 'local_path')