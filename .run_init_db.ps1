import app as A
A.app.config['WTF_CSRF_ENABLED'] = False
A.init_db()
print('db ok')
