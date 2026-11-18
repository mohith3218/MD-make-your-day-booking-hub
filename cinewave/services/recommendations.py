CINEMATCH_GENRE_KEYWORDS = {
    'Action': ('action', 'fight', 'combat', 'warrior', 'war', 'battle', 'army', 'mission', 'stunt', 'chase', 'vigilante', 'gangster', 'assassin'),
    'Adventure': ('adventure', 'journey', 'expedition', 'treasure', 'quest', 'exploration'),
    'Comedy': ('comedy', 'comedian', 'comic', 'laugh', 'humorous', 'funny', 'satire', 'entertainer'),
    'Drama': ('drama', 'family drama', 'emotional', 'relationship', 'struggle'),
    'Fantasy & Sci-Fi': ('sci-fi', 'science fiction', 'space', 'alien', 'future', 'universe', 'magic', 'fantasy', 'myth', 'supernatural'),
    'Horror': ('horror', 'ghost', 'haunted', 'demon', 'terrifying', 'fear'),
    'Mystery & Thriller': ('thriller', 'suspense', 'crime', 'mystery', 'police', 'investigation', 'murder', 'detective'),
    'Romance': ('romance', 'romantic', 'love story', 'lovers', 'wedding', 'heartbreak'),
}

CINEMATCH_MOODS = {
    'lighthearted': ('FUN',),
    'intense': ('THRILL', 'ACTION', 'MIND_BENDING'),
    'emotional': ('EMOTIONAL', 'DRAMA', 'ROMANCE'),
    'adventurous': ('ACTION', 'THRILL', 'MIND_BENDING'),
}

import re
from ..models import Movie, MovieRating, Watchlist



def cinematch_genres(movie):
    text_content = f'{movie.title or ""} {movie.description or ""}'.casefold()
    found = []
    for genre, keywords in CINEMATCH_GENRE_KEYWORDS.items():
        if any(re.search(r'(?<![a-z0-9])' + re.escape(keyword) + r'(?![a-z0-9])', text_content)
               for keyword in keywords):
            found.append(genre)
    return found


def cinematch_preferences(user_id):
    """Build lightweight taste signals from saves and the user's 4–5-star ratings."""
    saved_ids = {row.movie_id for row in Watchlist.query.filter_by(user_id=user_id).all()}
    rated = MovieRating.query.filter_by(user_id=user_id).all()
    positive_ids = {row.movie_id for row in rated if row.rating >= 4.0}
    disliked_ids = {row.movie_id for row in rated if row.rating <= 2.0}
    positive_movies = Movie.query.filter(
        Movie.id.in_(saved_ids | positive_ids)
    ).all() if saved_ids or positive_ids else []
    negative_movies = Movie.query.filter(Movie.id.in_(disliked_ids)).all() if disliked_ids else []

    def tally(movies):
        moods, genres, languages = {}, {}, {}
        for movie in movies:
            for mood in movie.moods:
                mood_code = str(mood).upper()
                moods[mood_code] = moods.get(mood_code, 0) + 1
            for genre in cinematch_genres(movie):
                genres[genre] = genres.get(genre, 0) + 1
            language = (movie.language or '').strip().casefold()
            if language:
                languages[language] = languages.get(language, 0) + 1
        return moods, genres, languages

    positive_moods, positive_genres, positive_languages = tally(positive_movies)
    negative_moods, negative_genres, _ = tally(negative_movies)
    return (positive_moods, positive_genres, positive_languages), (negative_moods, negative_genres), saved_ids, len(positive_movies)
