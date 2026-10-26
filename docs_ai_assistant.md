# AI assistant notes

The chat endpoint now uses the existing `ai_booking_assistant` module to process messages and return interactive cards/prompts. It builds a small movie + theatre + showtime context from the database each request and passes wallet balance + username when the user is authenticated.

Seat suggestion and movie review summary endpoints were checked for wiring; the review summary endpoint now reads from `MovieRating.review`.
