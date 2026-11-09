from pathlib import Path
import uvicorn

if __name__ == '__main__':
    root=Path(__file__).resolve().parent
    print(f'项目：{root}')
    print('网页工作台：http://127.0.0.1:8000')
    uvicorn.run('backend.main:app',host='127.0.0.1',port=8000,log_level='info')
