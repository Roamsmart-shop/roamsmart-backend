# test_africastalking.py
"""
Test script for Africa's Talking SMS Integration
Run this script to test if your Africa's Talking setup is working
"""

import os
import sys
import requests
import json
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configuration
BASE_URL = os.environ.get('BASE_URL', 'http://localhost:5000')
API_KEY = os.environ.get('AFRICASTALKING_API_KEY', '')
USERNAME = os.environ.get('AFRICASTALKING_USERNAME', 'sandbox')
SENDER_ID = os.environ.get('AFRICASTALKING_SENDER_ID', 'Roamsmart')

# Test phone number (use your own number for testing)
TEST_PHONE = os.environ.get('TEST_PHONE_NUMBER', '0553841216')  # Replace with your number

# Colors for output
GREEN = '\033[92m'
RED = '\033[91m'
YELLOW = '\033[93m'
BLUE = '\033[94m'
RESET = '\033[0m'

def print_section(title):
    """Print a section header"""
    print(f"\n{BLUE}{'='*60}{RESET}")
    print(f"{BLUE}{title:^60}{RESET}")
    print(f"{BLUE}{'='*60}{RESET}\n")

def print_success(message):
    """Print success message"""
    print(f"{GREEN}✅ {message}{RESET}")

def print_error(message):
    """Print error message"""
    print(f"{RED}❌ {message}{RESET}")

def print_info(message):
    """Print info message"""
    print(f"{YELLOW}ℹ️  {message}{RESET}")

def test_environment_variables():
    """Test 1: Check if environment variables are set"""
    print_section("TEST 1: Environment Variables")
    
    if API_KEY and API_KEY != 'mock_key':
        print_success(f"AFRICASTALKING_API_KEY found: {API_KEY[:20]}...")
    else:
        print_error("AFRICASTALKING_API_KEY not found or is mock")
        return False
    
    if USERNAME:
        print_success(f"AFRICASTALKING_USERNAME: {USERNAME}")
    else:
        print_error("AFRICASTALKING_USERNAME not set")
        return False
    
    if SENDER_ID:
        print_success(f"AFRICASTALKING_SENDER_ID: {SENDER_ID}")
    else:
        print_info("AFRICASTALKING_SENDER_ID not set, using default")
    
    return True

def test_africastalking_sdk():
    """Test 2: Test Africa's Talking SDK directly"""
    print_section("TEST 2: Africa's Talking SDK Direct Test")
    
    try:
        import africastalking
        print_success("Africa's Talking SDK imported successfully")
        
        # Initialize
        africastalking.initialize(USERNAME, API_KEY)
        print_success(f"Initialized with username: {USERNAME}")
        
        # Test SMS
        sms = africastalking.SMS
        print_success("SMS service initialized")
        
        # Check if we can send (without actually sending)
        print_info("SDK is ready. You can now send SMS.")
        return True
        
    except ImportError as e:
        print_error(f"Failed to import africastalking: {e}")
        print_info("Run: pip install africastalking")
        return False
    except Exception as e:
        print_error(f"Failed to initialize: {e}")
        return False

def test_send_sms_direct():
    """Test 3: Send a test SMS directly using Africa's Talking SDK"""
    print_section("TEST 3: Send Test SMS (Direct)")
    
    if not TEST_PHONE or TEST_PHONE == '0553841216':
        print_error("Please set TEST_PHONE_NUMBER in .env file")
        print_info("Example: TEST_PHONE_NUMBER=0241234567")
        return False
    
    print_info(f"Will send test SMS to: {TEST_PHONE}")
    
    try:
        import africastalking
        africastalking.initialize(USERNAME, API_KEY)
        sms = africastalking.SMS
        
        # Format phone number
        phone = TEST_PHONE
        if phone.startswith('0'):
            phone = phone[1:]
        if not phone.startswith('233'):
            phone = '233' + phone
        
        message = "Test SMS from Roamsmart - Your Africa's Talking integration is working!"
        
        print_info(f"Sending to: {phone}")
        print_info(f"Message: {message}")
        
        response = sms.send(message, [phone])
        
        print_success(f"Response received: {json.dumps(response, indent=2)}")
        
        # Check response
        if response.get('SMSMessageData', {}).get('Recipients'):
            recipients = response['SMSMessageData']['Recipients']
            if recipients and len(recipients) > 0:
                status = recipients[0].get('status', '')
                if status == 'Success':
                    print_success("SMS sent successfully!")
                    return True
                else:
                    print_error(f"SMS status: {status}")
                    return False
        
        return True
        
    except Exception as e:
        print_error(f"Failed to send SMS: {e}")
        return False

def test_api_endpoint():
    """Test 4: Test the API endpoint (if server is running)"""
    print_section("TEST 4: API Endpoint Test")
    
    # First, login to get token
    print_info("Attempting to login to get auth token...")
    
    try:
        # Login
        login_response = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={
                "email": "admin@roamsmart.shop",
                "password": "admin123"
            },
            headers={"Content-Type": "application/json"}
        )
        
        if login_response.status_code == 200:
            data = login_response.json()
            token = data.get('token')
            print_success("Login successful, token obtained")
            
            # Test SMS endpoint
            print_info(f"Sending test SMS via API to: {TEST_PHONE}")
            
            sms_response = requests.post(
                f"{BASE_URL}/api/test/sms",
                json={
                    "phone": TEST_PHONE,
                    "message": "Test SMS from Roamsmart API endpoint!"
                },
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {token}"
                }
            )
            
            if sms_response.status_code == 200:
                result = sms_response.json()
                if result.get('success'):
                    print_success("API test successful!")
                    return True
                else:
                    print_error(f"API error: {result.get('error', 'Unknown error')}")
                    return False
            else:
                print_error(f"API returned status code: {sms_response.status_code}")
                return False
                
        else:
            print_error(f"Login failed: {login_response.status_code}")
            print_info("Make sure your Flask server is running on port 5000")
            return False
            
    except requests.exceptions.ConnectionError:
        print_error(f"Cannot connect to {BASE_URL}")
        print_info("Make sure your Flask server is running")
        return False
    except Exception as e:
        print_error(f"API test failed: {e}")
        return False

def test_verification_code():
    """Test 5: Test verification code generation and SMS"""
    print_section("TEST 5: Verification Code Test")
    
    if not TEST_PHONE or TEST_PHONE == '0553841216':
        print_error("Please set TEST_PHONE_NUMBER in .env file")
        return False
    
    try:
        import africastalking
        import random
        
        africastalking.initialize(USERNAME, API_KEY)
        sms = africastalking.SMS
        
        # Generate random 6-digit code
        code = str(random.randint(100000, 999999))
        
        # Format phone
        phone = TEST_PHONE
        if phone.startswith('0'):
            phone = phone[1:]
        if not phone.startswith('233'):
            phone = '233' + phone
        
        message = f"Your Roamsmart verification code is: {code}. Valid for 10 minutes."
        
        print_info(f"Sending verification code {code} to {TEST_PHONE}")
        
        response = sms.send(message, [phone])
        
        if response.get('SMSMessageData', {}).get('Recipients'):
            recipients = response['SMSMessageData']['Recipients']
            if recipients and len(recipients) > 0:
                status = recipients[0].get('status', '')
                if status == 'Success':
                    message_id = recipients[0].get('messageId', 'N/A')
                    print_success(f"Verification code sent successfully! Message ID: {message_id}")
                    print_info(f"Code sent: {code} (for testing purposes)")
                    return True
                else:
                    print_error(f"Failed to send. Status: {status}")
                    return False
        
        return False
        
    except Exception as e:
        print_error(f"Failed to send verification code: {e}")
        return False

def main():
    """Run all tests"""
    print_section("AFRICA'S TALKING SMS TEST SUITE")
    print_info(f"Testing configuration:")
    print_info(f"  Base URL: {BASE_URL}")
    print_info(f"  Username: {USERNAME}")
    print_info(f"  Sender ID: {SENDER_ID}")
    print_info(f"  Test Phone: {TEST_PHONE}")
    
    results = []
    
    # Run tests
    results.append(("Environment Variables", test_environment_variables()))
    results.append(("SDK Import", test_africastalking_sdk()))
    
    # Ask user if they want to send actual SMS
    print_section("SEND ACTUAL SMS?")
    print_info("The following tests will send REAL SMS messages and may incur charges.")
    response = input("Do you want to continue? (y/N): ").lower()
    
    if response == 'y':
        results.append(("Direct SMS Test", test_send_sms_direct()))
        results.append(("Verification Code Test", test_verification_code()))
        results.append(("API Endpoint Test", test_api_endpoint()))
    else:
        print_info("Skipping SMS sending tests")
    
    # Print summary
    print_section("TEST SUMMARY")
    
    passed = sum(1 for _, r in results if r)
    total = len(results)
    
    for name, result in results:
        if result:
            print_success(f"{name}: PASSED")
        else:
            print_error(f"{name}: FAILED")
    
    print(f"\n{'='*60}")
    print(f"Total: {passed}/{total} tests passed")
    
    if passed == total:
        print_success("\n🎉 All tests passed! Africa's Talking is configured correctly!")
    else:
        print_error(f"\n⚠️ {total - passed} test(s) failed. Please check your configuration.")
        print_info("\nTroubleshooting tips:")
        print_info("1. Check your .env file has AFRICASTALKING_API_KEY")
        print_info("2. Make sure you're using 'sandbox' username for testing")
        print_info("3. Verify your internet connection")
        print_info("4. Check that your API key is active and has credits")
        print_info("5. Ensure phone number format is correct (e.g., 024XXXXXXX)")
    
    print()

if __name__ == "__main__":
    main()