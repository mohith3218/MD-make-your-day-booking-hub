# Movie review spoilers

An eligible viewer can mark a written movie review as containing spoilers. The movie review page omits the title and text of that review until the reader chooses **Reveal spoilers**. The same completed-booking check applies to the reveal request. **Hide spoilers** returns the review to its collapsed display.

The feature extends the existing `MovieRating` records. Legacy ratings without a booking link remain in the database and are excluded from the written-review page and its averages. An eligible viewer can publish a new draft in their existing record.
