import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / '源码_开源版'))
import app as backend
from hongguo_device import credentials, DeviceConfigurationError, register, PARSER_DEVICE_PROFILE, make_identity


class HongguoSetupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.runtime = patch.object(backend.parser_module, 'get_runtime_base_dir', return_value=self.root)
        self.environment = patch.dict(os.environ, {}, clear=True)
        self.environment.start()
        self.runtime.start()
        self.client = backend.app.test_client()
        backend.write_local_config({'device_id': 'MAC-SERIAL', 'install_id': 'hardware-id', 'download_path': str(self.root / 'videos')})

    def tearDown(self):
        self.runtime.stop()
        self.environment.stop()
        self.temp.cleanup()

    def test_invalid_saved_ids_are_not_reported_as_configured(self):
        response = self.client.get('/api/config')
        self.assertFalse(response.json['configured'])
        self.assertIn('digits only', response.json['configuration_error'])
        self.assertNotIn('MAC-SERIAL', response.get_data(as_text=True))

    def test_invalid_saves_preserve_configuration(self):
        before = backend.read_local_config()
        for body in [[], None, {'device_id': 'MacSerial', 'install_id': '123'}, {'device_id': '123', 'install_id': '0'}, {'device_id': True, 'install_id': '123'}, {'device_id': '１２３', 'install_id': '456'}]:
            response = self.client.post('/api/config', json=body)
            self.assertEqual(response.status_code, 400)
            self.assertEqual(backend.read_local_config(), before)

    def test_setup_saves_service_ids_and_preserves_folder(self):
        with patch.object(backend, 'register_hongguo', return_value={'device_id': '123456789', 'install_id': '987654321'}) as registration:
            response = self.client.post('/api/config/setup')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(backend.read_local_config()['device_id'], '123456789')
        self.assertEqual(backend.read_local_config()['download_path'], str(self.root / 'videos'))
        self.assertTrue(self.client.get('/api/config').json['configured'])
        registration.assert_called_once()
        with patch.object(backend, 'register_hongguo') as registration:
            self.assertEqual(self.client.post('/api/config/setup').status_code, 200)
            registration.assert_not_called()

    def test_failure_retains_credentials_and_registration_identity(self):
        with patch.object(backend, 'register_hongguo', side_effect=ValueError('private response with IDs')) as registration:
            for _ in range(2):
                response = self.client.post('/api/config/setup')
                self.assertEqual(response.status_code, 502)
                self.assertNotIn('private response', response.get_data(as_text=True))
            self.assertEqual(registration.call_args_list[0].args[1], registration.call_args_list[1].args[1])
        self.assertEqual(backend.read_local_config()['device_id'], 'MAC-SERIAL')

    def test_manual_save_during_registration_wins(self):
        def register_values(*args):
            self.client.post('/api/config', json={'device_id': '111', 'install_id': '222'})
            return {'device_id': '333', 'install_id': '444'}
        with patch.object(backend, 'register_hongguo', side_effect=register_values):
            self.assertEqual(self.client.post('/api/config/setup').status_code, 409)
        self.assertEqual(backend.read_local_config()['device_id'], '111')

    def test_remote_origin_and_duplicate_setup_are_rejected(self):
        with patch.object(backend, 'register_hongguo') as registration:
            self.assertEqual(self.client.post('/api/config/setup', headers={'Origin': 'https://example.com'}).status_code, 403)
            self.assertEqual(self.client.post('/api/config/setup', environ_overrides={'REMOTE_ADDR': '192.0.2.1'}).status_code, 403)
            with backend.DEVICE_SETUP_LOCK:
                self.assertEqual(self.client.post('/api/config/setup').status_code, 409)
            registration.assert_not_called()

    def test_invalid_environment_override_does_not_register(self):
        with patch.dict(os.environ, {'DUANJU_DEVICE_ID': 'invalid'}), patch.object(backend, 'register_hongguo') as registration:
            self.assertEqual(self.client.post('/api/config/setup').status_code, 400)
            registration.assert_not_called()

    def test_invalid_ids_stop_before_network_or_series_fallback(self):
        with patch.object(backend.parser_module, 'curl_request') as network, patch.object(backend.parser_module, 'get_hongguo_series_detail') as detail:
            with self.assertRaises(DeviceConfigurationError):
                backend.parser_module.handle_video_request('7697015096681172030')
            network.assert_not_called()
            detail.assert_not_called()
        response = self.client.get('/hg?vid=7697015096681172030')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json['code'], 'device_configuration')

    def test_upstream_service_error_is_preserved_without_raw_response(self):
        with self.assertRaisesRegex(ValueError, 'service error 110001'):
            backend.parser_module.extract_fallback_api({'Code': 110001, 'Message': 'private details'}, '123')
        with self.assertRaisesRegex(ValueError, 'service error 110001'):
            backend.parser_module.extract_fallback_api({'BaseResp': {'StatusCode': 110001}}, '123')
        with self.assertRaises(ValueError):
            backend.parser_module.extract_fallback_api([], '123')

    def test_registration_validates_service_response_and_profile(self):
        post = Mock(return_value=Mock(json=lambda: {'device_id': 123, 'install_id': 456}))
        values = register(PARSER_DEVICE_PROFILE, make_identity(), post=post)
        self.assertEqual(values['device_id'], '123')
        self.assertEqual(values['install_id'], '456')
        self.assertEqual(post.call_args.kwargs['params']['aid'], '8662')
        post.return_value.json = lambda: {'device_id': 0, 'install_id': 0}
        with self.assertRaises(DeviceConfigurationError):
            register(PARSER_DEVICE_PROFILE, make_identity(), post=post)
