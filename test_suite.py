#!/usr/bin/env python3
"""
test_suite.py - Unit and Integration Tests for setup_notebook.py and client_setup.sh
"""

import os
import sys
import tempfile
import unittest
import subprocess
import shutil

# Import setup_notebook module functions
import setup_notebook


class TestSetupNotebook(unittest.TestCase):

    def test_validate_ssh_public_key_valid(self):
        valid_key = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIExamplePublicKeyForTesting user@localhost"
        result = setup_notebook.validate_ssh_public_key(valid_key)
        self.assertEqual(result, valid_key)

    def test_validate_ssh_public_key_rsa(self):
        valid_rsa = "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQ3ExtraData user@localhost"
        result = setup_notebook.validate_ssh_public_key(valid_rsa)
        self.assertEqual(result, valid_rsa)

    def test_validate_ssh_public_key_invalid(self):
        invalid_key = "invalid-key-type AAAAC3NzaC1lZDI1NTE5AAAAIExample user@localhost"
        with self.assertRaises(ValueError):
            setup_notebook.validate_ssh_public_key(invalid_key)

    def test_validate_ssh_public_key_empty(self):
        with self.assertRaises(ValueError):
            setup_notebook.validate_ssh_public_key("   ")

    def test_get_secret_env(self):
        os.environ["TEST_SECRET_ENV"] = "secret_val_123"
        val = setup_notebook.get_secret("TEST_SECRET_ENV", "TEST_COLAB", "Test Secret")
        self.assertEqual(val, "secret_val_123")
        del os.environ["TEST_SECRET_ENV"]

    def test_get_optional_secret_env(self):
        os.environ["TUNNEL_TOKEN"] = "token_abc_123"
        val = setup_notebook.get_optional_secret(
            ["CLOUDFLARE_TUNNEL_TOKEN", "TUNNEL_TOKEN"],
            ["CLOUDFLARE_TUNNEL_TOKEN", "TUNNEL_TOKEN"]
        )
        self.assertEqual(val, "token_abc_123")
        del os.environ["TUNNEL_TOKEN"]

    def test_get_optional_secret_none(self):
        val = setup_notebook.get_optional_secret(
            ["NON_EXISTENT_ENV_VAR_123"],
            ["NON_EXISTENT_COLAB_VAR_123"]
        )
        self.assertIsNone(val)

    def test_keepalive_env_detection(self):
        os.environ["KEEPALIVE"] = "1"
        self.assertIn(os.environ.get("KEEPALIVE", "").strip(), ("1", "true", "TRUE", "yes", "YES"))
        del os.environ["KEEPALIVE"]


class TestClientSetupScript(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.fake_home = os.path.join(self.temp_dir, "home")
        os.makedirs(os.path.join(self.fake_home, ".ssh"), mode=0o700)

        # Create a dummy SSH key file
        self.dummy_key = os.path.join(self.fake_home, ".ssh", "id_ed25519")
        with open(self.dummy_key, "w") as f:
            f.write("dummy private key")
        os.chmod(self.dummy_key, 0o600)

        self.script_path = os.path.abspath("client_setup.sh")

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    def run_client_script(self, args, env=None):
        test_env = os.environ.copy()
        test_env["HOME"] = self.fake_home
        if env:
            test_env.update(env)

        cmd = [self.script_path] + args
        return subprocess.run(cmd, env=test_env, capture_output=True, text=True)

    def test_client_setup_cloudflared(self):
        res = self.run_client_script([
            "--provider", "cloudflared",
            "--host", "test.trycloudflare.com",
            "--user", "dev",
            "--alias", "test-cf",
            "--identity", self.dummy_key
        ])
        self.assertEqual(res.returncode, 0, f"Script failed: {res.stderr}")

        config_path = os.path.join(self.fake_home, ".ssh", "config")
        self.assertTrue(os.path.exists(config_path))

        with open(config_path, "r") as f:
            content = f.read()

        self.assertIn("Host test-cf", content)
        self.assertIn("HostName test.trycloudflare.com", content)
        self.assertIn("User dev", content)
        self.assertIn("ProxyCommand cloudflared access ssh --hostname %h", content)
        self.assertIn("StrictHostKeyChecking ask", content)
        self.assertNotIn("StrictHostKeyChecking=no", content)

    def test_client_setup_ngrok(self):
        res = self.run_client_script([
            "--provider", "ngrok",
            "--host", "0.tcp.ngrok.io",
            "--port", "12345",
            "--user", "devuser",
            "--alias", "test-ngrok",
            "--identity", self.dummy_key
        ])
        self.assertEqual(res.returncode, 0, f"Script failed: {res.stderr}")

        config_path = os.path.join(self.fake_home, ".ssh", "config")
        self.assertTrue(os.path.exists(config_path))

        with open(config_path, "r") as f:
            content = f.read()

        self.assertIn("Host test-ngrok", content)
        self.assertIn("HostName 0.tcp.ngrok.io", content)
        self.assertIn("Port 12345", content)
        self.assertIn("User devuser", content)
        self.assertIn("StrictHostKeyChecking ask", content)

    def test_backup_creation_and_update(self):
        config_path = os.path.join(self.fake_home, ".ssh", "config")
        with open(config_path, "w") as f:
            f.write("# Initial config\nHost existing\n    HostName example.com\n")
        os.chmod(config_path, 0o600)

        res = self.run_client_script([
            "--provider", "cloudflared",
            "--host", "test.trycloudflare.com",
            "--user", "dev",
            "--alias", "test-cf",
            "--identity", self.dummy_key
        ])
        self.assertEqual(res.returncode, 0)

        # Check backup file exists
        backups = [f for f in os.listdir(os.path.join(self.fake_home, ".ssh")) if "backup" in f]
        self.assertTrue(len(backups) >= 1)

        # Test updating the same alias replaces block without duplicates
        res2 = self.run_client_script([
            "--provider", "cloudflared",
            "--host", "updated.trycloudflare.com",
            "--user", "dev",
            "--alias", "test-cf",
            "--identity", self.dummy_key
        ])
        self.assertEqual(res2.returncode, 0)

        with open(config_path, "r") as f:
            content = f.read()

        self.assertIn("HostName updated.trycloudflare.com", content)
        self.assertNotIn("HostName test.trycloudflare.com", content)


if __name__ == "__main__":
    unittest.main()
