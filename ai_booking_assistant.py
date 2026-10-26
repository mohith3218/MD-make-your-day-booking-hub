"""
AI Booking Assistant for CineWave
================================
Intelligent conversational assistant that helps users discover movies, find showtimes,
recommend best seats, and book tickets directly through the chat with zero external dependencies.
"""

import json
import re
from datetime import datetime, date, timedelta


def parse_entities(prompt):
    """
    Extracts entities such as movie title keywords, seat count, seat class,
    theater preference, and time hints from natural language prompt.
    """
    text = prompt.lower().strip()
    entities = {
        'seat_count': None,
        'seat_class': None,
        'movie_query': None,
        'theater_query': None,
        'date_query': None
    }

    # Extract seat count (e.g. "2 tickets", "3 seats", "for 4", "single ticket", "a ticket", "couple")
    seat_words = {
        'one': 1, 'single': 1, 'a': 1, 'an': 1, 'two': 2, 'three': 3,
        'four': 4, 'five': 5, 'six': 6, 'couple': 2, 'pair': 2,
        'first': 1, 'second': 2, 'third': 3, 'fourth': 4
    }
    count_match = re.search(r'\b(\d+)\s*(?:tickets?|seats?|people|persons?|members?)?\b', text)
    if count_match and count_match.group(1).isdigit():
        val = int(count_match.group(1))
        if 1 <= val <= 10:
            entities['seat_count'] = val

    if not entities['seat_count']:
        for word, num in seat_words.items():
            if re.search(rf'\b{word}\s+(?:tickets?|seats?|people|persons?)?\b', text) or text.endswith(f"for {word}"):
                entities['seat_count'] = num
                break

    # Extract seat class preference
    if any(k in text for k in ['recliner', 'sofa', 'vip', 'luxury', 'insignia', 'couch']):
        entities['seat_class'] = 'RECLINER'
    elif any(k in text for k in ['prime', 'executive', 'premium', 'gold', 'balcony']):
        entities['seat_class'] = 'PRIME'
    elif any(k in text for k in ['classic', 'normal', 'budget', 'standard', 'economy']):
        entities['seat_class'] = 'CLASSIC'

    # Date queries
    if 'today' in text or 'tonight' in text:
        entities['date_query'] = 'today'
    elif 'tomorrow' in text:
        entities['date_query'] = 'tomorrow'

    return entities


def find_best_seats(layout, booked_seats, held_seats, count=2, preferred_class=None):
    """
    Intelligently recommends the best consecutive seats in the theatre.
    Favors middle-to-back rows and central seat numbers.
    """
    unavailable = set(booked_seats) | set(held_seats)
    classes = layout.get('classes', [])
    if not classes:
        return []

    # Sort classes by preference if specified
    ordered_classes = classes
    if preferred_class:
        ordered_classes = sorted(
            classes,
            key=lambda c: 0 if preferred_class.upper() in c.get('code', '').upper() or preferred_class.upper() in c.get('name', '').upper() else 1
        )

    for cls in ordered_classes:
        rows = cls.get('rows', [])
        # Prefer middle-to-back rows for optimal viewing angle
        for row in reversed(rows):
            label = row.get('label', '')
            total_in_row = row.get('count', 0)
            blocked = set(row.get('blocked', []))

            # Build list of valid seat numbers in row
            valid_seats = []
            for num in range(1, total_in_row + 1):
                s_id = f"{label}{num}"
                if s_id not in blocked:
                    valid_seats.append(s_id)

            # Find consecutive available run closest to center
            mid_idx = len(valid_seats) // 2
            candidate_runs = []
            for i in range(len(valid_seats) - count + 1):
                run = valid_seats[i:i + count]
                if all(s not in unavailable for s in run):
                    # Score run by distance to center
                    dist_to_center = abs((i + count / 2.0) - mid_idx)
                    candidate_runs.append((dist_to_center, run))

            if candidate_runs:
                candidate_runs.sort(key=lambda x: x[0])
                return candidate_runs[0][1]

    # If consecutive seats not found in one row, pick any available seats closest to center
    all_avail = []
    for cls in ordered_classes:
        for row in cls.get('rows', []):
            label = row.get('label', '')
            blocked = set(row.get('blocked', []))
            for num in range(1, row.get('count', 0) + 1):
                s_id = f"{label}{num}"
                if s_id not in blocked and s_id not in unavailable:
                    all_avail.append(s_id)
                if len(all_avail) == count:
                    return all_avail

    return all_avail[:count]


def process_chat_message(user_prompt, history=None, context_data=None, user_info=None):
    """
    Main conversational AI entrypoint. Analyzes intent and generates friendly text
    and rich interactive cards for seamless ticket booking.
    """
    prompt = user_prompt.strip()
    p_lower = prompt.lower()
    entities = parse_entities(prompt)

    movies = (context_data or {}).get('movies', [])
    theaters = (context_data or {}).get('theaters', [])
    showtimes = (context_data or {}).get('showtimes', [])
    user_wallet = (user_info or {}).get('wallet_balance', None)

    # 1. GREETING INTENT
    if any(p_lower.startswith(k) or p_lower == k for k in ['hi', 'hello', 'hey', 'start', 'help', 'namaste']):
        text = (
            "👋 **Hi there! I'm your CineWave AI Booking Assistant.**\n\n"
            "I can help you instantly find movies, check showtimes in Vizag, pick the best seats, "
            "and book tickets directly here. What would you like to watch today?"
        )
        actions = [{
            'type': 'movie_cards',
            'title': '🔥 Trending in Vizag Theaters',
            'items': [{
                'id': m['id'],
                'title': m['title'],
                'genre': m.get('genre', 'Drama'),
                'rating': m.get('rating', 8.5),
                'language': m.get('language', 'Telugu'),
                'action_prompt': f"Book tickets for {m['title']}"
            } for m in movies[:4]]
        }]
        return {'response': text, 'actions': actions, 'intent': 'greeting'}

    # 2. WALLET & BALANCE INTENT
    if any(k in p_lower for k in ['wallet', 'balance', 'my money', 'recharge', 'bonus']):
        if user_wallet is not None:
            text = (
                f"💳 **Your CineWave Wallet Balance:** **₹{user_wallet:.2f}**\n\n"
                "You can use this balance for instant 1-click checkout with zero payment gateway delays. "
                "Would you like to recharge or book tickets now?"
            )
        else:
            text = (
                "💳 **CineWave Wallet:**\n\n"
                "Every new user receives a **₹500 welcome bonus** credited to their wallet! "
                "You can log in to view your balance or recharge via **Account → Wallet**."
            )
        return {
            'response': text,
            'actions': [{
                'type': 'quick_replies',
                'options': [
                    {'label': '🎟️ Book a Movie', 'prompt': 'What movies are playing?'},
                    {'label': '💰 Open Wallet', 'url': '/wallet'}
                ]
            }],
            'intent': 'wallet'
        }

    # 3. CANCELLATION & REFUND INTENT
    if any(k in p_lower for k in ['cancel', 'refund', 'cancellation']):
        text = (
            "🔄 **CineWave Cancellation & Wallet Refund Policy:**\n\n"
            "• You can cancel tickets anytime **before the showtime starts**.\n"
            "• **85% - 90%** of the ticket value is refunded directly back to your CineWave Wallet instantly!\n"
            "• Visit your **Profile / My Bookings** to select a booking and request a 1-click instant refund."
        )
        return {
            'response': text,
            'actions': [{
                'type': 'quick_replies',
                'options': [
                    {'label': '📋 View My Bookings', 'url': '/profile'},
                    {'label': '🎟️ Book New Tickets', 'prompt': 'Show movie listings'}
                ]
            }],
            'intent': 'cancellation'
        }

    # 4. DIRECT BOOKING INTENT (User wants to book a specific movie or showtime)
    matched_movie = None
    for m in movies:
        if m['title'].lower() in p_lower or any(word in p_lower for word in m['title'].lower().split() if len(word) > 3):
            matched_movie = m
            break

    # If user wants to book or matched a movie
    if any(k in p_lower for k in ['book', 'ticket', 'showtime', 'watch']) or matched_movie:
        if matched_movie:
            # Look for available showtimes for this movie
            movie_shows = [s for s in showtimes if s.get('movie_id') == matched_movie['id']]
            if movie_shows:
                seats_phrase = f" for **{entities['seat_count']}**" if entities['seat_count'] else ""
                class_phrase = f" ({entities['seat_class']} class)" if entities['seat_class'] else ""
                text = (
                    f"🎬 **{matched_movie['title']}** ({matched_movie.get('language', 'Telugu')} • ⭐ {matched_movie.get('rating', 8.5)})\n\n"
                    f"Great pick! Here are the available showtimes in Vizag theatres{seats_phrase}{class_phrase}. "
                    "Select a showtime to proceed with seat reservation:"
                )
                show_items = []
                for s in movie_shows[:6]:
                    show_items.append({
                        'showtime_id': s['id'],
                        'theater': s.get('theater', 'Multiplex'),
                        'screen': s.get('screen_label', 'Audi 1'),
                        'time': s.get('show_time', '6:30 PM'),
                        'date': s.get('show_date', 'Today'),
                        'seats_left': s.get('seats_left', 50),
                        'book_url': f"/book/{s['id']}",
                        'direct_count': entities['seat_count'] or 2,
                        'direct_class': entities['seat_class'] or 'PRIME'
                    })
                return {
                    'response': text,
                    'actions': [{
                        'type': 'showtime_cards',
                        'movie_id': matched_movie['id'],
                        'movie_title': matched_movie['title'],
                        'items': show_items
                    }],
                    'intent': 'showtime_selection'
                }
            else:
                text = (
                    f"🎬 **{matched_movie['title']}** is currently listed in our catalog! "
                    "You can view complete movie details and upcoming schedules below:"
                )
                return {
                    'response': text,
                    'actions': [{
                        'type': 'quick_replies',
                        'options': [
                            {'label': f"View {matched_movie['title']}", 'url': f"/movie/{matched_movie['id']}"},
                            {'label': 'Browse Other Movies', 'prompt': 'What movies are playing today?'}
                        ]
                    }],
                    'intent': 'movie_detail'
                }

    # 5. THEATRE QUERY INTENT
    if any(k in p_lower for k in ['theater', 'theatre', 'cinemas', 'inox', 'jagadamba', 'aaa', 'location']):
        text = (
            "🏛️ **Featured Visakhapatnam Theatres:**\n\n"
            "• **AAA Cinemas** (Inorbit Mall, Madhurawada - 8 screens, 70ft LED Screen)\n"
            "• **INOX Varun Beach** (Beach Road - INSIGNIA VIP Recliners)\n"
            "• **Jagadamba 70MM** (Jagadamba Junction - 886-seat iconic hall)\n"
            "• **Cinepolis Sreekanya Cineglitz** (Madhurawada - 4 Audi Multiplex)\n\n"
            "Which movie or cinema would you like to book for?"
        )
        return {
            'response': text,
            'actions': [{
                'type': 'quick_replies',
                'options': [
                    {'label': '🎬 Show Movies', 'prompt': 'What movies are playing?'},
                    {'label': '📍 Inorbit Mall (AAA)', 'prompt': 'Showtimes at AAA Cinemas'},
                    {'label': '🌊 INOX Varun Beach', 'prompt': 'Showtimes at INOX Varun Beach'}
                ]
            }],
            'intent': 'theaters'
        }

    # 6. MOVIE DISCOVERY / RECOMMENDATION FALLBACK
    if movies:
        top_movie = movies[0]
        text = (
            f"🍿 **Currently Playing in Vizag:**\n\n"
            f"We have **{len(movies)}** popular movies showing across 23 theatres today. "
            f"Our #1 recommendation is **{top_movie['title']}** (⭐ {top_movie.get('rating', 8.5)}).\n\n"
            "Click a movie below to book your seats right now!"
        )
        actions = [{
            'type': 'movie_cards',
            'title': 'Now Showing',
            'items': [{
                'id': m['id'],
                'title': m['title'],
                'genre': m.get('genre', 'Action/Drama'),
                'rating': m.get('rating', 8.5),
                'language': m.get('language', 'Telugu'),
                'action_prompt': f"Book tickets for {m['title']}"
            } for m in movies[:5]]
        }]
    else:
        text = (
            "Welcome to **CineWave**! Explore top movies, premium screens, and real-time seat booking. "
            "How can I assist you with your booking today?"
        )
        actions = []

    return {
        'response': text,
        'actions': actions,
        'intent': 'discovery'
    }


def generate_movie_review_summary(movie_title, reviews):
    """
    Summarizes movie reviews into audience consensus and highlights with zero external keys.
    """
    if not reviews:
        return {
            "summary": f"Audience reviews for '{movie_title}' will appear here as viewers complete their screenings.",
            "sentiment": "Highly Anticipated",
            "score": "8.8/10"
        }

    # Deduplicate reviews so repeated posts from the same user don't skew the read
    unique_reviews = []
    seen = set()
    for r in reviews:
        key = r.strip().lower()
        if key and key not in seen:
            seen.add(key)
            unique_reviews.append(r.strip())
    reviews = unique_reviews

    num_revs = len(reviews)
    sample_text = " ".join(reviews[:6]).lower()
    
    positives = sum(1 for word in ['good', 'great', 'awesome', 'masterpiece', 'superb', 'loved', 'blockbuster', 'must watch', 'excellent', 'amazing', 'fantastic'] if word in sample_text)
    negatives = sum(1 for word in ['bad', 'boring', 'waste', 'disappointing', 'weak', 'horrible', 'poor', 'slow', 'dragged'] if word in sample_text)
    
    if num_revs == 0:
        sentiment = "Sparse Reviews"
        score = "N/A"
    elif positives >= 2 and negatives == 0:
        sentiment = "Overwhelmingly Positive"
        score = "4.8/5"
    elif positives >= negatives:
        sentiment = "Positive & Recommended"
        score = "4.2/5"
    else:
        sentiment = "Mixed Reactions"
        score = "3.5/5"

    # Build a summary that reflects the actual review language instead of a canned sentence
    recap_words = []
    for r in reviews[:4]:
        if len(r) > 24:
            recap_words.append(r[:48].rstrip() + ('…' if len(r) > 48 else ''))
    if recap_words:
        highlights = " | ".join(recap_words)
        summary = (
            f"Across {num_revs} review(s), audiences are talking about: {highlights}."
        )
    else:
        summary = (
            f"Based on {num_revs} community review(s), audiences are sharing their thoughts on '{movie_title}'."
        )

    return {
        "summary": summary,
        "sentiment": sentiment,
        "score": score
    }
