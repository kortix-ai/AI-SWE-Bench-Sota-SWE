import os
import boto3
import botocore

def download_s3_directory(bucket_name, prefix, local_dir):
    """
    Download a directory from a public S3 bucket without credentials
    
    Args:
        bucket_name (str): Name of the S3 bucket
        prefix (str): S3 prefix/directory to download from
        local_dir (str): Local directory to download files to
    """
    # Create an S3 client without credentials for public access
    s3_client = boto3.client(
        's3',
        config=botocore.config.Config(signature_version=botocore.UNSIGNED)
    )
    
    try:
        # List objects in the bucket under the prefix
        paginator = s3_client.get_paginator('list_objects_v2')
        objects = paginator.paginate(Bucket=bucket_name, Prefix=prefix)
        
        for page in objects:
            if "Contents" not in page:
                raise Exception(f"No objects found in {bucket_name}/{prefix}")
                
            for obj in page['Contents']:
                # Get the relative path
                rel_path = obj['Key']
                # Create the local file path
                local_file_path = f"{local_dir}/{rel_path}"
                
                # Create directory if it doesn't exist
                os.makedirs(os.path.dirname(local_file_path), exist_ok=True)
                
                # Download the file
                print(f"Downloading {rel_path}")
                s3_client.download_file(bucket_name, rel_path, local_file_path)
                
    except botocore.exceptions.ClientError as e:
        if e.response['Error']['Code'] == 'NoSuchBucket':
            print(f"Error: Bucket {bucket_name} does not exist")
        elif e.response['Error']['Code'] == 'NoSuchKey':
            print(f"Error: Prefix {prefix} does not exist")
        else:
            print(f"Error: {e}")
        return False
        
    return True

# Example usage:
if __name__ == "__main__":
    bucket = "swe-bench-experiments"
    # example
    # prefix = "lite/20241025_OpenHands-CodeAct-2.1-sonnet-20241022/trajs"
    local_dir = "./trajs"
    
    success = download_s3_directory(bucket, prefix, local_dir)
    if success:
        print("Download completed successfully")