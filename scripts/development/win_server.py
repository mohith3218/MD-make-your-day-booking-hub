import os
os.environ['FLASK_DEBUG'] = '1'
import app as A

A.app.config['WTF_CSRF_ENABLED'] = False

def main():
    print('LISTEN http://127.0.0.1:5000')
    A.app.run(host='127.0.0.1', port=5000)

if __name__ == '__main__':
    main()
