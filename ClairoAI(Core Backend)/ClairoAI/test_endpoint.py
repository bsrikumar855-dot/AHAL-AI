import requests
import time
import sys

url = 'http://localhost:8000/api/v1/repo/analyze'
repo_url = 'https://github.com/encode/starlette' # arbitrary small repo

print(f'Triggering /analyze for {repo_url}...')
response = requests.post(url, json={'repo_url': repo_url})
if response.status_code != 202:
    print(f'Failed to start job: {response.status_code} {response.text}')
    sys.exit(1)

job_id = response.json().get('job_id')
print(f'Job ID: {job_id}')

while True:
    status_url = f'http://localhost:8000/api/v1/status/{job_id}'
    status_res = requests.get(status_url)
    if status_res.status_code != 200:
        print(f'Failed to get status: {status_res.status_code} {status_res.text}')
        break
    
    status_data = status_res.json()
    status = status_data.get('status')
    print(f'Status: {status}')
    
    if status in ['completed', 'failed']:
        print('Final Data:', status_data)
        break
        
    time.sleep(3)
