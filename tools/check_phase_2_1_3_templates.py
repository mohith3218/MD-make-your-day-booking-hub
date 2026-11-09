"""Check JavaScript after Jinja rendering, using only an isolated QA snapshot."""
import re
import subprocess

import phase_2_1_3_qa as qa

client = qa.A.app.test_client()
with client.session_transaction() as session:
    session['_user_id'] = str(qa.qa_user_id)
    session['_fresh'] = True
checked = 0
for name, show_id in qa.show_ids.items():
    routes = [f'/book/{show_id}/vr-preview']
    if name == 'inox':
        routes.append(f'/book/{show_id}')
    for route in routes:
        response = client.get(route)
        assert response.status_code == 200, (route, response.status_code)
        for source in re.findall(r'<script\b[^>]*>(.*?)</script>', response.get_data(as_text=True), re.S | re.I):
            if not source.strip():
                continue
            target = qa.QA_DIR / f'syntax-{checked}.js'
            target.write_text(source, encoding='utf-8')
            subprocess.run(['node', '--check', str(target)], check=True, capture_output=True)
            checked += 1
print(f'PASS: {checked} rendered inline JavaScript blocks across seeded previews and booking page')
