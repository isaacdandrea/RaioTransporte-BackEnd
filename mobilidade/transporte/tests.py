from datetime import date, time

from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient
from unittest.mock import patch

from transporte.algorithms.raio_alcance import carregar_conexoes
from transporte.models import Calendar, Frequency, Route, Stop, StopTime, Trip


class ConnectionBuilderTests(TestCase):
    def setUp(self):
        Calendar.objects.create(
            service_id="S1",
            monday=True,
            tuesday=True,
            wednesday=True,
            thursday=True,
            friday=True,
            saturday=False,
            sunday=False,
            start_date=date(2024, 1, 1),
            end_date=date(2024, 12, 31),
        )

        self.stop_a = Stop.objects.create(
            stop_id="A",
            stop_name="Stop A",
            stop_lat=-23.0,
            stop_lon=-46.0,
        )
        self.stop_b = Stop.objects.create(
            stop_id="B",
            stop_name="Stop B",
            stop_lat=-23.001,
            stop_lon=-46.001,
        )
        self.stop_c = Stop.objects.create(
            stop_id="C",
            stop_name="Stop C",
            stop_lat=-23.002,
            stop_lon=-46.002,
        )

        self.route = Route.objects.create(
            route_id="R1",
            agency=None,
            route_short_name="R1",
            route_long_name="Route 1",
            route_type=3,
        )

        self.trip = Trip.objects.create(
            trip_id="T1",
            route=self.route,
            service_id="S1",
            trip_headsign="Centro",
            direction_id=0,
        )

        StopTime.objects.bulk_create(
            [
                StopTime(
                    trip=self.trip,
                    stop=self.stop_a,
                    arrival_time=time(8, 0),
                    departure_time=time(8, 0),
                    stop_sequence=1,
                ),
                StopTime(
                    trip=self.trip,
                    stop=self.stop_b,
                    arrival_time=time(8, 10),
                    departure_time=time(8, 11),
                    stop_sequence=2,
                ),
                StopTime(
                    trip=self.trip,
                    stop=self.stop_c,
                    arrival_time=time(8, 22),
                    departure_time=time(8, 22),
                    stop_sequence=3,
                ),
            ]
        )

    def test_connections_without_frequency(self):
        conns, idx = carregar_conexoes("monday", horizon_end=600)

        self.assertEqual(len(conns), 2)
        self.assertIn(self.stop_a.stop_id, idx)
        self.assertIn(self.stop_b.stop_id, idx)

    def test_connections_with_frequency_extension(self):
        Frequency.objects.create(
            trip=self.trip,
            start_time=time(9, 0),
            end_time=time(9, 20),
            headway_secs=600,
        )

        conns, _ = carregar_conexoes("monday", horizon_end=600)

        self.assertGreater(len(conns), 2)
        headway_departures = [
            c.dep_min
            for c in conns
            if c.dep_stop == self.stop_a.stop_id and c.dep_min >= 540
        ]
        self.assertTrue(headway_departures)


@override_settings(API_SHARED_SECRET="test-key")
class RaioDeAlcanceAuthTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.url = reverse("raio-alcance")

        self.patcher_cache_get = patch(
            "transporte.views.cache_service.get_cached_response",
            return_value=None,
        )
        self.patcher_cache_store = patch(
            "transporte.views.cache_service.store_response",
            return_value=None,
        )
        self.patcher_algorithm = patch(
            "transporte.views.calcular_raio", return_value={"features": []}
        )

        self.mock_cache_get = self.patcher_cache_get.start()
        self.mock_cache_store = self.patcher_cache_store.start()
        self.mock_algorithm = self.patcher_algorithm.start()

    def tearDown(self):
        patch.stopall()

    def test_missing_api_key_returns_unauthorized(self):
        response = self.client.post(
            self.url,
            {"lat": -23.0, "lon": -46.0, "tempo": 15},
            format="json",
        )

        self.assertEqual(response.status_code, 401)

    def test_valid_api_key_allows_access(self):
        response = self.client.post(
            self.url,
            {
                "lat": -23.0,
                "lon": -46.0,
                "tempo": 15,
                "presetsDia": "DEFAULT",
            },
            format="json",
            HTTP_X_API_KEY="test-key",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"features": []})
        self.mock_algorithm.assert_called_once()
