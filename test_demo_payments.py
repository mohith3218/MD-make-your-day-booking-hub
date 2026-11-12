"""Demo policy and production WSGI preflight tests; never connect to a database."""
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

import payments


class DemoPaymentTests(unittest.TestCase):
    def test_production_requires_explicit_opt_in(self):
        with patch.dict(os.environ, {'APP_ENV': 'production'}, clear=True):
            self.assertFalse(payments.mock_payments_enabled())
            with self.assertRaises(payments.PaymentGatewayError):
                payments.create_order(100, 'disabled')
            for setting in ('false', '', '0', 'unexpected'):
                os.environ['DEMO_PAYMENTS_ENABLED'] = setting
                self.assertFalse(payments.mock_payments_enabled())
            os.environ['DEMO_PAYMENTS_ENABLED'] = 'true'
            order = payments.create_order(100, 'enabled')
            self.assertEqual(order['gateway'], 'mock')
            self.assertEqual(json.loads(order['raw'])['settled'], False)

    def test_demo_signatures_are_private_and_bound_to_both_ids(self):
        with patch.dict(os.environ, {'APP_ENV': 'testing', 'DEMO_PAYMENTS_ENABLED': 'true',
                                    'SECRET_KEY': 'private-demo-secret'}, clear=True):
            order = payments.create_order(123.45, 'fixture')
            result = payments.simulate_payment(order['order_id'])
            self.assertTrue(payments.verify_signature(order['order_id'], result['payment_id'], result['signature']))
            self.assertFalse(payments.verify_signature('order_mock_other', result['payment_id'], result['signature']))
            self.assertFalse(payments.verify_signature(order['order_id'], 'pay_mock_other', result['signature']))
            self.assertFalse(payments.verify_signature('external_order', result['payment_id'], result['signature']))
            self.assertFalse(payments.verify_signature(order['order_id'], result['payment_id'], 'é' * 64))
            self.assertFalse(payments.verify_signature(order['order_id'], result['payment_id'], None))
            os.environ['SECRET_KEY'] = 'different-secret'
            self.assertFalse(payments.verify_signature(order['order_id'], result['payment_id'], result['signature']))

    def test_invalid_amounts_and_methods_are_rejected(self):
        with patch.dict(os.environ, {'DEMO_PAYMENTS_ENABLED': 'true'}):
            for amount in (float('nan'), float('inf'), 1e308, '', None, 0, -1, 0.001):
                with self.assertRaises(payments.PaymentGatewayError):
                    payments.create_order(amount, 'invalid')
            order = payments.create_order(50, 'fixture')
            with self.assertRaises(payments.PaymentGatewayError):
                payments.simulate_payment(order['order_id'], method='external')

    def test_all_existing_simulation_methods_and_fee_rules(self):
        with patch.dict(os.environ, {'DEMO_PAYMENTS_ENABLED': 'true'}):
            for method in payments.DEMO_METHODS:
                order = payments.create_order(200, method)
                self.assertTrue(payments.simulate_payment(order['order_id'], method)['ok'])
                self.assertFalse(payments.simulate_payment(order['order_id'], method, False)['ok'])
            self.assertEqual(payments.compute_amounts(800, 2)['total'], 847.2)

    def test_production_wsgi_and_read_only_startup_without_provider_credentials(self):
        code = '''
import json, socket
from unittest.mock import patch
with patch.object(socket.socket, 'connect', side_effect=AssertionError('Network forbidden in tests')):
    import app as A
    from importlib.util import spec_from_file_location, module_from_spec
    @A.app.get('/__production_probe')
    def probe():
        return {'mode': A.payments.gateway_name(), 'secure': A.app.config['SESSION_COOKIE_SECURE']}
    with A.app.app_context():
        A.validate_production_config()
        with patch('database_health.check_database', return_value={'ok':True}) as health, \\
             patch.object(A.db, 'create_all', side_effect=AssertionError('No DDL allowed')), \\
             patch.object(A, 'seed_vizag_theaters', side_effect=AssertionError('No seeding allowed')):
            spec = spec_from_file_location('qa_gunicorn', 'gunicorn.conf.py')
            config = module_from_spec(spec); spec.loader.exec_module(config)
            config.on_starting(None)
            assert health.call_count == 1
    client = A.app.test_client()
    result = client.get('/__production_probe')
    assert result.status_code == 200
    assert 'Strict-Transport-Security' in result.headers
    if not A.payments.mock_payments_enabled():
        assert client.post('/pay/simulate/missing').status_code == 403
    assert client.post('/pay/webhook').status_code == 404
    print(json.dumps(result.get_json()))
'''
        for enabled, mode in (('true', 'mock'), ('', 'disabled')):
            env = dict(os.environ, APP_ENV='production', DEMO_PAYMENTS_ENABLED=enabled,
                       DATABASE_URL='postgresql+psycopg://fixture:fixture@127.0.0.1:1/fixture',
                       SECRET_KEY='isolated-production-test-secret-at-least-32-characters', PYTHONUTF8='1')
            result = subprocess.run([sys.executable, '-c', code], env=env,
                                    cwd=Path(__file__).resolve().parent,
                                    capture_output=True, text=True, encoding='utf-8', timeout=40)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout), {'mode':mode, 'secure':True})


if __name__ == '__main__':
    unittest.main()
