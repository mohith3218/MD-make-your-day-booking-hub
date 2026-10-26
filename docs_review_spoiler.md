# Review and spoiler notes

The rating endpoint now stores the `review` text on the existing `MovieRating.review` column and keeps the standalone `has_spoiler` flag. Auto-detection runs only when the user did not explicitly toggle the Spoiler Shield checkbox.

The movie page renders spoiler reviews inside a tappable spoiler shield block, with the review text blurred until the user taps "Tap to reveal". Non-spoiler reviews render normally.

The AI audience summary pulls from `MovieRating.review`, deduplicates repeated posts, and reflects the actual review snippets instead of a canned one-liner.
