
import argparse
import subprocess
import os

def get_instance_docker_image(instance_id: str) -> str:
    """Get the docker image name for a specific instance."""
    DOCKER_IMAGE_PREFIX = os.environ.get('EVAL_DOCKER_IMAGE_PREFIX', 'docker.io/xingyaoww/')
    image_name = 'sweb.eval.x86_64.' + instance_id
    image_name = image_name.replace('__', '_s_')  # To comply with Docker naming conventions
    return (DOCKER_IMAGE_PREFIX.rstrip('/') + '/' + image_name).lower()

def run_docker_bash(instance_id: str):
    docker_image = get_instance_docker_image(instance_id)
    cmd = ['docker', 'run', '-it', docker_image, '/bin/bash']
    subprocess.run(cmd, check=True)

def main():
    parser = argparse.ArgumentParser(description='Run Docker container interactively for a given instance_id.')
    parser.add_argument('instance_id', type=str, help='Instance ID to run docker bash')
    args = parser.parse_args()
    run_docker_bash(args.instance_id)

if __name__ == '__main__':
    main()