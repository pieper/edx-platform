from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.test import TestCase
from django.test.client import Client, RequestFactory
from django.test.utils import override_settings
from mock import Mock, patch

from notification_prefs import NOTIFICATION_PREF_KEY
from notification_prefs.views import ajax_enable, ajax_disable, unsubscribe
from student.tests.factories import UserFactory
from user_api.models import UserPreference


@override_settings(SECRET_KEY="test secret key")
class NotificationPrefViewTest(TestCase):
    INITIALIZATION_VECTOR = "\x00" * 16

    @classmethod
    def setUpClass(cls):
        # Make sure global state is set up appropriately
        Client().get("/")

    def setUp(self):
        self.user = UserFactory.create(username="testuser")
        # Tokens are intentionally hard-coded instead of computed to help us
        # avoid breaking existing links.
        self.tokens = {
            self.user: "AAAAAAAAAAAAAAAAAAAAAA8mMQo96FZfb1YKv1R5X6s=",
            # Username with length equal to AES block length to test padding
            UserFactory.create(username="sixteencharsuser"):
            "AAAAAAAAAAAAAAAAAAAAAPxPWCuI2Ay9TATBVnfw7eIj-hUh6erQ_-VkbDqHqm8D",
            # Even longer username
            UserFactory.create(username="thisusernameissoveryverylong"):
            "AAAAAAAAAAAAAAAAAAAAAPECbYqPI7_W4mRF8LbTaHuHt3tNXPggZ1Bke-zDyEiZ",
            # Non-ASCII username
            UserFactory.create(username=u"\u4e2d\u56fd"):
            "AAAAAAAAAAAAAAAAAAAAAMjfGAhZKIZsI3L-Z7nflTA="
        }
        self.request_factory = RequestFactory()

    def create_prefs(self):
        """Create all test preferences in the database"""
        for (user, token) in self.tokens.items():
            UserPreference.objects.create(user=user, key=NOTIFICATION_PREF_KEY, value=token)

    def assertPrefValid(self, user):
        """Ensure that the correct preference for the user is persisted"""
        self.assertEqual(
            UserPreference.objects.get(user=user, key=NOTIFICATION_PREF_KEY).value,
            self.tokens[user]
        )

    def assertNotPrefExists(self, user):
        """Ensure that the user does not have a persisted preference"""
        self.assertFalse(
            UserPreference.objects.filter(user=user, key=NOTIFICATION_PREF_KEY).exists()
        )

    # AJAX enable view

    def test_ajax_enable_get(self):
        request = self.request_factory.get("dummy")
        request.user = self.user
        response = ajax_enable(request)
        self.assertEqual(response.status_code, 405)
        self.assertNotPrefExists(self.user)

    def test_ajax_enable_anon_user(self):
        request = self.request_factory.post("dummy")
        request.user = AnonymousUser()
        self.assertRaises(PermissionDenied, ajax_enable, request)
        self.assertNotPrefExists(self.user)

    @patch("Crypto.Random.new")
    def test_ajax_enable_success(self, mock_random_new):
        mock_stream = Mock()
        mock_stream.read.return_value = self.INITIALIZATION_VECTOR
        mock_random_new.return_value = mock_stream

        def test_user(user):
            request = self.request_factory.post("dummy")
            request.user = user
            response = ajax_enable(request)
            self.assertEqual(response.status_code, 204)
            self.assertPrefValid(user)

        for user in self.tokens.keys():
            test_user(user)

    def test_ajax_enable_already_enabled(self):
        self.create_prefs()
        request = self.request_factory.post("dummy")
        request.user = self.user
        response = ajax_enable(request)
        self.assertEqual(response.status_code, 204)
        self.assertPrefValid(self.user)

    def test_ajax_enable_distinct_values(self):
        request = self.request_factory.post("dummy")
        request.user = self.user
        ajax_enable(request)
        other_user = UserFactory.create()
        request.user = other_user
        ajax_enable(request)
        self.assertNotEqual(
            UserPreference.objects.get(user=self.user, key=NOTIFICATION_PREF_KEY).value,
            UserPreference.objects.get(user=other_user, key=NOTIFICATION_PREF_KEY).value
        )

    # AJAX disable view

    def test_ajax_disable_get(self):
        self.create_prefs()
        request = self.request_factory.get("dummy")
        request.user = self.user
        response = ajax_disable(request)
        self.assertEqual(response.status_code, 405)
        self.assertPrefValid(self.user)

    def test_ajax_disable_anon_user(self):
        self.create_prefs()
        request = self.request_factory.post("dummy")
        request.user = AnonymousUser()
        self.assertRaises(PermissionDenied, ajax_disable, request)
        self.assertPrefValid(self.user)

    def test_ajax_disable_success(self):
        self.create_prefs()
        request = self.request_factory.post("dummy")
        request.user = self.user
        response = ajax_disable(request)
        self.assertEqual(response.status_code, 204)
        self.assertNotPrefExists(self.user)

    def test_ajax_disable_already_disabled(self):
        request = self.request_factory.post("dummy")
        request.user = self.user
        response = ajax_disable(request)
        self.assertEqual(response.status_code, 204)
        self.assertNotPrefExists(self.user)

    # Unsubscribe view

    def test_unsubscribe_post(self):
        request = self.request_factory.post("dummy")
        response = unsubscribe(request, "dummy")
        self.assertEqual(response.status_code, 405)

    def test_unsubscribe_invalid_token(self):
        def test_invalid_token(token, message):
            request = self.request_factory.get("dummy")
            self.assertRaisesRegexp(Http404, "^{}$".format(message), unsubscribe, request, token)

        # Invalid base64 encoding
        test_invalid_token("ZOMG INVALID BASE64 CHARS!!!", "base64url")
        test_invalid_token("Non-ASCII\xff", "base64url")
        test_invalid_token(self.tokens[self.user][:-1], "base64url")

        # Token not long enough to contain initialization vector
        test_invalid_token("AAAAAAAAAAA=", "initialization_vector")

        # Token length not a multiple of AES block length
        test_invalid_token(self.tokens[self.user][:-4], "aes")

        # Invalid padding (ends in 0 byte)
        # Encrypted value: "testuser" + "\x00" * 8
        test_invalid_token("AAAAAAAAAAAAAAAAAAAAAMoazRI7ePLjEWXN1N7keLw=", "padding")

        # Invalid padding (ends in byte > 16)
        # Encrypted value: "testusertestuser"
        test_invalid_token("AAAAAAAAAAAAAAAAAAAAAC6iLXGhjkFytJoJSBJZzJ4=", "padding")

        # Invalid padding (entire string is padding)
        # Encrypted value: "\x10" * 16
        test_invalid_token("AAAAAAAAAAAAAAAAAAAAANRGw8HDEmlcLVFawgY9wI8=", "padding")

        # Nonexistent user
        # Encrypted value: "nonexistentuser\x01"
        test_invalid_token("AAAAAAAAAAAAAAAAAAAAACpyUxTGIrUjnpuUsNi7mAY=", "username")

    def test_unsubscribe_success(self):
        self.create_prefs()

        def test_user(user):
            request = self.request_factory.get("dummy")
            request.user = AnonymousUser()
            response = unsubscribe(request, self.tokens[user])
            self.assertEqual(response.status_code, 200)
            self.assertNotPrefExists(user)

        for user in self.tokens.keys():
            test_user(user)

    def test_unsubscribe_twice(self):
        self.create_prefs()
        request = self.request_factory.get("dummy")
        request.user = AnonymousUser()
        unsubscribe(request, self.tokens[self.user])
        response = unsubscribe(request, self.tokens[self.user])
        self.assertEqual(response.status_code, 200)
        self.assertNotPrefExists(self.user)
