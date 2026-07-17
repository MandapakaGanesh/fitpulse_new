import sys
import unittest
import mongomock
from unittest.mock import patch

# Mock pymongo.MongoClient with mongomock.MongoClient
@patch("pymongo.MongoClient", mongomock.MongoClient)
def run_tests():
    # Reload user_store to apply the mocked pymongo client on import
    if "ml_core.user_store" in sys.modules:
        del sys.modules["ml_core.user_store"]
        
    from ml_core import user_store
    
    class TestUserStoreMongo(unittest.TestCase):
        def setUp(self):
            # Clear collections
            user_store.users_col.delete_many({})
            user_store.runs_col.delete_many({})
            
        def test_seed_admin(self):
            user_store.seed_admin_user()
            admin = user_store.users_col.find_one({"_id": "admin"})
            self.assertIsNotNone(admin)
            self.assertTrue(user_store.verify_user("admin", "fitpulse2026"))
            
        def test_register_and_verify(self):
            # Non-existent user
            self.assertFalse(user_store.verify_user("testuser", "pass"))
            
            # Register user
            self.assertTrue(user_store.register_user("testuser", "securepass123"))
            
            # Duplicate register
            self.assertFalse(user_store.register_user("testuser", "otherpass"))
            
            # Verify correct login
            self.assertTrue(user_store.verify_user("testuser", "securepass123"))
            self.assertFalse(user_store.verify_user("testuser", "wrongpass"))
            
        def test_save_and_retrieve_runs(self):
            username = "brian_analyst"
            run_id = "test-run-uuid-12345"
            meta = {
                "timestamp": 1234567.89,
                "anomaly_count": 5,
                "mean": 120.5,
                "sigma": 2.5,
                "eps": 0.8
            }
            pdf_data = b"This is a dummy PDF file content bytes stream."
            results = {"summary": "Passed", "metrics": [1, 2, 3]}
            
            user_store.save_user_run(username, run_id, meta, pdf_data, results)
            
            # List user runs
            runs = user_store.list_user_runs(username)
            self.assertEqual(len(runs), 1)
            self.assertEqual(runs[0]["run_id"], run_id)
            self.assertEqual(runs[0]["anomaly_count"], 5)
            
            # Retrieve PDF
            pdf_bytes = user_store.get_user_run_pdf(username, run_id)
            self.assertEqual(pdf_bytes, pdf_data)
            
            # Load analysis results
            loaded = user_store.load_user_run_results(username, run_id)
            self.assertEqual(loaded, results)
            
    # Run the suite
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(TestUserStoreMongo)
    runner = unittest.TextTestRunner(stream=sys.stdout, verbosity=2)
    result = runner.run(suite)
    
    if not result.wasSuccessful():
        sys.exit(1)
    else:
        print("MongoDB driver unit tests: ALL PASSED")

if __name__ == "__main__":
    run_tests()
