"""Theatre-first workflows on disposable SQLite; operator data is never opened."""
from datetime import date, datetime, timedelta, timezone
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parent
_temporary = tempfile.TemporaryDirectory(prefix='theatre-discovery-')
_url = 'sqlite:///' + (Path(_temporary.name) / 'test.db').as_posix()
os.environ.update(APP_ENV='testing', DATABASE_URL=_url, TEST_DATABASE_URL=_url,
                  SECRET_KEY='isolated-theatre-discovery-fixture', SMTP_HOST='',
                  SMTP_USERNAME='', SMTP_PASSWORD='', TMDB_API_KEY='',
                  DEMO_PAYMENTS_ENABLED='true', SESSION_COOKIE_SECURE='0')

import app as A
from sqlalchemy import event, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import OperationalError
from theatre_discovery import cinema_now


class DiscoveryHTML(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.links, self.inputs = [], {}
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'a':
            self.links.append(attrs)
        if tag == 'input' and attrs.get('name'):
            self.inputs[attrs['name']] = attrs.get('value', '')


class TheatreDiscoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with A.app.app_context():
            assert Path(A.db.engine.url.database).resolve().is_relative_to(Path(_temporary.name))
            @event.listens_for(A.db.engine, 'connect')
            def enforce_foreign_keys(connection, record):
                connection.execute('PRAGMA foreign_keys=ON')

    @classmethod
    def tearDownClass(cls):
        with A.app.app_context():
            A.db.session.remove()
            A.db.engine.dispose()
        _temporary.cleanup()

    def setUp(self):
        self.context = A.app.app_context()
        self.context.push()
        A.db.session.remove()
        A.db.drop_all()
        A.db.create_all()
        A.app.config.update(TESTING=True, SESSION_PROTECTION='basic')
        self.today = cinema_now().date()
        self.day = self.today + timedelta(days=2)
        self.first = A.Theater(name='Coastal Cinema', location='Beach Road', city='Visakhapatnam', address='Waterfront')
        self.second = A.Theater(name='Hill Cinema', location='Hill Road', city='Visakhapatnam')
        self.empty = A.Theater(name='Quiet Cinema', location='Old Town', city='Visakhapatnam')
        self.no_screens = A.Theater(name='Future Cinema', city='Other City')
        layout = {'classes': [{'code':'STD', 'name':'Standard', 'price':200,
                              'rows':[{'label':'A', 'count':4, 'blocked':['A4']},
                                      {'label':'B', 'count':2}]}]}
        self.screen = A.Screen(theater=self.first, name='Coastal 1', screen_type='2D', layout_json=json.dumps(layout))
        self.three_d = A.Screen(theater=self.first, name='Coastal 3D', screen_type='3D', layout_json=json.dumps(layout))
        self.other_screen = A.Screen(theater=self.second, name='Hill 1', screen_type='2D', layout_json=json.dumps(layout))
        self.movie = A.Movie(title='Coastal Action', description='Action film', duration=120,
                             language='Telugu', certificate='U/A')
        self.hindi = A.Movie(title='Hindi Drama', description='A drama', duration=150, language='Hindi')
        self.other_movie = A.Movie(title='Hill Exclusive', description='Only at Hill', duration=110, language='English')
        self.unscheduled = A.Movie(title='Not Scheduled Anywhere', description='No shows', duration=90)
        self.user = A.User(username='discovery_user', password_hash='fixture', email_verified=True)
        A.db.session.add_all([self.first,self.second,self.empty,self.no_screens,self.screen,self.three_d,
                              self.other_screen,self.movie,self.hindi,self.other_movie,self.unscheduled,self.user])
        A.db.session.flush()
        self.show = A.Showtime(movie=self.movie, screen=self.screen, theater='Legacy mismatched name',
                               show_date=self.day, show_time='7:30 PM')
        self.early = A.Showtime(movie=self.movie, screen=self.three_d, theater=self.first.name,
                                show_date=self.day, show_time='10:00 AM')
        self.hindi_show = A.Showtime(movie=self.hindi, screen=self.three_d, theater=self.first.name,
                                     show_date=self.day, show_time='2:00 PM')
        self.next_day = A.Showtime(movie=self.movie, screen=self.screen, theater=self.first.name,
                                   show_date=self.day + timedelta(days=1), show_time='11:30 PM')
        self.other_show = A.Showtime(movie=self.other_movie, screen=self.other_screen, theater=self.second.name,
                                     show_date=self.day, show_time='5:00 PM')
        self.past = A.Showtime(movie=self.other_movie, screen=self.screen, theater=self.first.name,
                               show_date=self.today - timedelta(days=1), show_time='10:00 AM')
        self.invalid_time = A.Showtime(movie=self.other_movie, screen=self.screen, theater=self.first.name,
                                       show_date=self.day, show_time='not-a-time')
        self.legacy = A.Showtime(movie=self.other_movie, theater=self.first.name,
                                 show_date=self.day, show_time='6:00 PM')
        A.db.session.add_all([self.show,self.early,self.hindi_show,self.next_day,self.other_show,
                              self.past,self.invalid_time,self.legacy,A.Wallet(user=self.user,balance=2000)])
        A.db.session.commit()
        self.client = A.app.test_client()
        self.detail = f'/theatres/{self.first.id}'
        self.sign_in()

    def tearDown(self):
        A.db.session.remove()
        self.context.pop()

    def sign_in(self):
        with self.client.session_transaction() as state:
            state['_user_id'] = self.user.alternative_id
            state['_fresh'] = True

    def seat_links(self, html):
        return [item['href'] for item in DiscoveryHTML(html).links
                if 'td-seat-link' in item.get('class', '')]

    def test_directory_search_matches_only_theatre_names(self):
        html = self.client.get('/theatres?q=coAsTaL').text
        self.assertIn('Coastal Cinema', html)
        self.assertNotIn('Hill Cinema', html)
        self.assertIn('Coastal 1', html)
        self.assertIn('Coastal 3D', html)
        self.assertNotIn('td-venue-card', self.client.get('/theatres?q=Waterfront').text)

    def test_search_escapes_wildcards_and_matches_case_insensitively(self):
        self.assertNotIn('Coastal Cinema', self.client.get('/theatres?q=Waterfront').text)
        html = self.client.get('/theatres?q=%25').text
        self.assertIn('No cinemas match', html)
        self.assertNotIn('td-venue-card', html)
        self.assertIn('No cinemas match', self.client.get("/theatres?q=' OR 1=1--").text)

    def test_invalid_and_duplicate_filters(self):
        for url in ['/theatres?q=' + 'a'*121, '/theatres?q=a&q=b', self.detail+'?date=2026-02-30',
                    self.detail+'?date=invalid', self.detail+'?screen=abc', self.detail+'?time=25:00',
                    self.detail+'?date=2026-01-01&date=2026-01-02']:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 400)

    def test_detail_only_has_movies_actually_scheduled_at_selected_theatre(self):
        html = self.client.get(self.detail).text
        self.assertIn('Coastal Action', html)
        self.assertIn('Hindi Drama', html)
        self.assertNotIn('Hill Exclusive', html)
        self.assertNotIn('Not Scheduled Anywhere', html)
        self.assertNotIn('Legacy mismatched name', html)
        self.assertIn('IST', html)
        self.assertIn('Mood tags', html)

    def test_date_filter_and_empty_date(self):
        html = self.client.get(self.detail+'?date='+self.next_day.show_date.isoformat()).text
        links = self.seat_links(html)
        self.assertEqual(links, [f'/theatres/{self.first.id}/shows/{self.next_day.id}/book'])
        self.assertIn('Ends 01:30 AM', html)
        self.assertIn((self.next_day.show_date+timedelta(days=1)).strftime('%d %b'), html)
        empty = self.client.get(self.detail+'?date=2000-01-01')
        self.assertEqual(empty.status_code, 200)
        self.assertIn('No upcoming screenings', empty.text)

    def test_movie_language_format_screen_and_time_filters(self):
        response = self.client.get(self.detail+f'/movies/{self.movie.id}?format=3D&screen={self.three_d.id}&time=10:00&language=Telugu')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.seat_links(response.text), [f'/theatres/{self.first.id}/shows/{self.early.id}/book'])
        self.assertNotIn('Hindi Drama', response.text)
        self.assertEqual(self.client.get(self.detail+f'/movies/{self.other_movie.id}').status_code, 404)
        self.assertEqual(self.client.get(self.detail+f'?screen={self.other_screen.id}').status_code, 404)

    def test_empty_theatres_and_no_screen_legacy_show(self):
        for venue in (self.empty,self.no_screens):
            response = self.client.get(f'/theatres/{venue.id}')
            self.assertEqual(response.status_code, 200)
            self.assertIn('no upcoming shows', response.text)
            self.assertFalse(self.seat_links(response.text))
        self.assertEqual(self.client.get(f'/theatres/999999').status_code, 404)

    def test_actual_screen_relationship_overrides_legacy_name(self):
        response = self.client.get(f'/theatres/{self.first.id}/shows/{self.show.id}/book')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(parse_qs(urlsplit(response.location).query)['screen_id'], [str(self.screen.id)])
        wrong = self.client.get(f'/theatres/{self.second.id}/shows/{self.show.id}/book')
        self.assertEqual(wrong.status_code, 404)

    def test_sold_out_and_expired_holds(self):
        utc = datetime.now(timezone.utc).replace(tzinfo=None)
        ids = list(A.show_seat_prices(self.show))
        A.db.session.add_all([A.SeatHold(showtime_id=self.show.id,seat_id=seat,token='sold-out',
                                        expires_at=utc+timedelta(minutes=4)) for seat in ids])
        A.db.session.commit()
        html = self.client.get(self.detail+f'?screen={self.screen.id}').text
        self.assertIn('Sold out', html)
        self.assertNotIn(f'/shows/{self.show.id}/book', html)
        self.assertEqual(self.client.get(f'{self.detail}/shows/{self.show.id}/book').status_code, 409)
        A.SeatHold.query.update({A.SeatHold.expires_at:utc-timedelta(seconds=1)})
        A.db.session.commit()
        self.assertEqual(self.client.get(f'{self.detail}/shows/{self.show.id}/book').status_code, 302)

    def test_price_override_dynamic_factor_and_available_category(self):
        self.show.price_overrides_json = json.dumps({'STD':300})
        A.db.session.commit()
        html = self.client.get(self.detail+f'?screen={self.screen.id}').text
        # Two days ahead is the existing 10% early-bird rule.
        expected = A.price_seats(self.show,['A1'])[0]
        self.assertEqual(expected,270)
        self.assertIn('₹270.00',html)
        self.assertNotIn('A4',A.show_seat_prices(self.show))

    def test_booked_and_held_same_seat_count_once(self):
        A.db.session.add_all([A.BookedSeat(showtime_id=self.show.id,seat_id='A1'),
            A.SeatHold(showtime_id=self.show.id,seat_id='A1',token='overlap',
                       expires_at=datetime.now(timezone.utc).replace(tzinfo=None)+timedelta(minutes=2))])
        A.db.session.commit()
        html=self.client.get(self.detail+f'?screen={self.screen.id}').text
        self.assertIn('4 seats available',html)

    def test_starting_price_excludes_sold_out_cheapest_category(self):
        self.screen.layout = {'classes': [
            {'code':'STD','name':'Standard','price':100,'rows':[{'label':'A','count':1}]},
            {'code':'VIP','name':'Premium','price':400,'rows':[{'label':'C','count':5}]}]}
        A.db.session.add(A.BookedSeat(showtime_id=self.show.id,seat_id='A1'))
        A.db.session.commit()
        html=self.client.get(self.detail+f'?screen={self.screen.id}').text
        self.assertIn('₹360.00',html)
        self.assertNotIn('₹90.00',html)

    def test_query_count_does_not_grow_per_movie_or_screen(self):
        for i in range(10):
            movie=A.Movie(title=f'Extra Film {i}',description='Fixture',duration=90)
            A.db.session.add(A.Showtime(movie=movie,screen=self.screen,theater=self.first.name,
                                       show_date=self.day,show_time=f'{i+1}:00 PM'))
        A.db.session.commit()
        queries=[]
        def count(conn,cursor,statement,parameters,context,many):
            queries.append(statement)
        event.listen(A.db.engine,'before_cursor_execute',count)
        try:
            response=self.client.get(self.detail)
        finally:
            event.remove(A.db.engine,'before_cursor_execute',count)
        self.assertEqual(response.status_code,200)
        self.assertLessEqual(len(queries),8)

    def test_started_and_invalid_time_cannot_be_booked(self):
        self.sign_in()
        fixed = self.show.show_datetime + timedelta(minutes=1)
        with patch('cinewave.routes.main.cinema_now',return_value=fixed), \
             patch('cinewave.models.catalog.cinema_now',return_value=fixed), \
             patch('theatre_discovery.cinema_now',return_value=fixed):
            self.assertEqual(self.show.status,'live')
            self.assertEqual(self.client.get(f'{self.detail}/shows/{self.show.id}/book').status_code,409)
            self.assertEqual(self.client.post(f'/book/{self.show.id}',data={'selected_seats':'A1'}).status_code,302)
        self.assertEqual(self.invalid_time.status,'unavailable')
        self.assertEqual(self.client.get(f'{self.detail}/shows/{self.invalid_time.id}/book').status_code,409)
        self.assertEqual(A.Booking.query.count(),0)

    def test_removed_show_is_not_a_booking_option(self):
        show_id=self.show.id
        A.db.session.delete(self.show)
        A.db.session.commit()
        self.assertEqual(self.client.get(f'{self.detail}/shows/{show_id}/book').status_code,404)

    def test_tampered_booking_context_is_rejected_on_get_and_post(self):
        self.sign_in()
        for key,value in [('theatre_id',self.second.id),('screen_id',self.other_screen.id),('movie_id',self.other_movie.id)]:
            with self.subTest(key=key):
                self.assertEqual(self.client.get(f'/book/{self.show.id}?{key}={value}').status_code,404)
                self.assertEqual(self.client.post(f'/book/{self.show.id}',data={key:value,'selected_seats':'A1'}).status_code,404)
        self.assertEqual(self.client.get(f'/book/{self.show.id}?screen_id=abc').status_code,400)
        self.assertEqual(self.client.get(f'/book/{self.show.id}?screen_id=1&screen_id=2').status_code,400)
        self.assertEqual(A.Booking.query.count(),0)
        self.assertEqual(A.SeatHold.query.count(),0)

    def test_login_next_preserves_context(self):
        client=A.app.test_client()
        handoff=client.get(f'{self.detail}/shows/{self.show.id}/book')
        response=client.get(handoff.location)
        self.assertEqual(response.status_code,200)
        next_url=parse_qs(urlsplit(handoff.location).query)['next'][0]
        self.assertEqual(next_url, f'/theatres/{self.first.id}/shows/{self.show.id}/book')

    def test_complete_discovery_to_booking_payment_and_ticket(self):
        self.sign_in()
        link=self.seat_links(self.client.get(self.detail+f'?screen={self.screen.id}').text)[0]
        seat_page=self.client.get(link,follow_redirects=True)
        self.assertEqual(seat_page.status_code,200)
        inputs=DiscoveryHTML(seat_page.text).inputs
        self.assertEqual(inputs['screen_id'],str(self.screen.id))
        self.assertEqual(inputs['theatre_id'],str(self.first.id))
        self.assertIn('data-seat="A1"',seat_page.text)
        self.assertNotIn('data-seat="A4"',seat_page.text)
        inputs.update(selected_seats='A1',price='1',total_amount='1')
        reserve=self.client.post(f'/book/{self.show.id}',data=inputs)
        self.assertIn('/checkout/',reserve.location)
        booking=A.Booking.query.one()
        self.assertEqual(booking.showtime_id,self.show.id)
        self.assertEqual(booking.ticket_amount,A.price_seats(self.show,['A1'])[0])
        self.assertNotEqual(booking.total_amount,1)
        self.assertEqual(self.client.get(reserve.location).status_code,200)
        with patch('cinewave.services.seat.dispatch_ticket_delivery',return_value=False):
            gateway=self.client.post(f'/pay/gateway/{booking.reference}',data={'method':'upi'})
            self.assertEqual(gateway.status_code,303)
            self.assertEqual(self.client.get(gateway.location).status_code,200)
            paid=self.client.post(f'/pay/simulate/{booking.reference}',data={'outcome':'success'})
        self.assertIn('/ticket/',paid.location)
        self.assertEqual(self.client.get(paid.location).status_code,200)
        A.db.session.refresh(booking)
        self.assertEqual(booking.status,'PAID')

    def test_unavailable_or_other_screen_seat_is_rejected(self):
        self.sign_in()
        response=self.client.post(f'/book/{self.show.id}',data={'selected_seats':'Z99'})
        self.assertEqual(response.status_code,302)
        self.assertEqual(A.Booking.query.count(),0)

    def test_error_state_on_database_failure(self):
        with patch('flask_sqlalchemy.query.Query.all',side_effect=OperationalError('fixture',{},Exception('fixture'))):
            response=self.client.get('/theatres')
        self.assertEqual(response.status_code,503)
        self.assertIn('temporarily unavailable',response.text)
        self.assertNotIn('fixture',response.text)

    def test_templates_scripts_and_postgresql_query_compilation(self):
        for route in ['/theatres',self.detail,self.detail+f'/movies/{self.movie.id}']:
            response=self.client.get(route)
            self.assertEqual(response.status_code,200)
            for script in re.findall(r'<script\b[^>]*>(.*?)</script>',response.text,re.S):
                if script.strip():
                    result=subprocess.run(['node','--check'],input=script,text=True,
                                          encoding='utf-8',capture_output=True,timeout=20)
                    self.assertEqual(result.returncode,0,result.stderr)
        result=subprocess.run(['node','--check','static/js/theatre-discovery.js'],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        statement=(A.db.select(A.Showtime.id).join(A.Screen,A.Showtime.screen_id==A.Screen.id)
                   .where(A.Screen.theater_id==self.first.id,A.Showtime.show_date>=self.today))
        sql=str(statement.compile(dialect=postgresql.dialect()))
        self.assertIn('JOIN screen',sql)
        self.assertIn('theater_id',sql)

    def test_discovery_is_read_only_and_adds_no_tables(self):
        before={name:A.db.session.execute(text('SELECT COUNT(*) FROM "'+name+'"')).scalar()
                for name in A.db.metadata.tables}
        self.client.get('/theatres')
        self.client.get(self.detail)
        after={name:A.db.session.execute(text('SELECT COUNT(*) FROM "'+name+'"')).scalar()
               for name in A.db.metadata.tables}
        self.assertEqual(before,after)

    def test_timezone_is_independent_of_server_timezone(self):
        current=cinema_now()
        expected=datetime.now(timezone.utc).replace(tzinfo=None)+timedelta(hours=5,minutes=30)
        self.assertLess(abs((current-expected).total_seconds()),2)


if __name__=='__main__':
    unittest.main(verbosity=2)
