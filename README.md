# VERY IMPORTANT NOTES:

- This bot has not yet been tested with Questrade. **Use at your own risk.**
- This bot will only trade USD denominated non-halted securities priced greater than $1 with a market cap over 1B and average daily volume over 250k.
- As Questrade does not support selling or buying on close, this bot **MUST** remain active until the end of the trading day to properly close out positions.
- As a consequence of the above, this bot will close out **ALL** positions on your account within 15 minutes of the end of the trading day.
- None of the information contained here constitutes an offer (or solicitation of an offer) to buy or sell any currency, product or financial instrument, to make any investment, or to participate in any particular trading strategy.

# TODO

- Ditch Google Cloud, so this'll run anywhere (sorry Google)
- Memoize Questrade position IDs
- Break out some of the repeated code into functions

**Feel free to contribute!**

# Forked from Trump2Cash

This bot watches [Donald Trump's tweets](https://twitter.com/realDonaldTrump)
and waits for him to mention any publicly traded companies. When he does, it
uses sentiment analysis to determine whether his opinions are positive or
negative toward those companies. The bot then automatically executes trades on
the relevant stocks according to the expected market reaction. It also tweets
out a summary of its findings in real time at
[@Trump2Cash](https://twitter.com/Trump2Cash).

*You can read more about the background story [here](http://trump2cash.biz).*

The code is written in Python and is meant to run on a
[Google Compute Engine](https://cloud.google.com/compute/) instance. It uses the
[Twitter Streaming APIs](https://dev.twitter.com/streaming/overview) to get
notified whenever Trump tweets. The entity detection and sentiment analysis is
done using Google's
[Cloud Natural Language API](https://cloud.google.com/natural-language/) and the
[Wikidata Query Service](https://query.wikidata.org/) provides the company data.
The [Questrade API](http://www.questrade.com/api) does the stock trading.

The [`main`](main.py) module defines a callback where incoming tweets are
handled and starts streaming Trump's feed:

```python
def twitter_callback(tweet):
    companies = analysis.find_companies(tweet)
    if companies:
        trading.make_trades(companies)
        twitter.tweet(companies, tweet)

if __name__ == "__main__":
    twitter.start_streaming(twitter_callback)
```

The core algorithms are implemented in the [`analysis`](analysis.py) and
[`trading`](trading.py) modules. The former finds mentions of companies in the
text of the tweet, figures out what their ticker symbol is, and assigns a
sentiment score to them. The latter chooses a trading strategy, which is either
buy now and sell at close or sell short now and buy to cover at close. The
[`twitter`](twitter.py) module deals with streaming and tweeting out the
summary.

Follow these steps to run the code yourself:

### 1. Create VM instance

Check out the [quickstart](https://cloud.google.com/compute/docs/quickstart-linux)
to create a Cloud Platform project and a Linux VM instance with Compute Engine,
then SSH into it for the steps below. The predefined
[machine type](https://cloud.google.com/compute/docs/machine-types) `g1-small`
(1 vCPU, 1.7 GB memory) seems to work well.

### 2. Set up auth

The authentication keys for the different APIs are read from shell environment
variables. Each service has different steps to obtain them.

#### Twitter

Log in to your [Twitter](https://twitter.com/) account and
[create a new application](https://apps.twitter.com/app/new). Under the *Keys
and Access Tokens* tab for [your app](https://apps.twitter.com/) you'll find
the *Consumer Key* and *Consumer Secret*. Export both to environment variables:

```shell
export TWITTER_CONSUMER_KEY="<YOUR_CONSUMER_KEY>"
export TWITTER_CONSUMER_SECRET="<YOUR_CONSUMER_SECRET>"
```

If you want the tweets to come from the same account that owns the application,
simply use the *Access Token* and *Access Token Secret* on the same page. If
you want to tweet from a different account, follow the
[steps to obtain an access token](https://dev.twitter.com/oauth/overview). Then
export both to environment variables:

```shell
export TWITTER_ACCESS_TOKEN="<YOUR_ACCESS_TOKEN>"
export TWITTER_ACCESS_TOKEN_SECRET="<YOUR_ACCESS_TOKEN_SECRET>"
```

#### Google

Follow the
[Google Application Default Credentials instructions](https://developers.google.com/identity/protocols/application-default-credentials#howtheywork)
to create, download, and export a service account key.

```shell
export GOOGLE_APPLICATION_CREDENTIALS="/path/to/credentials-file.json"
```

You also need to [enable the Cloud Natural Language API](https://cloud.google.com/natural-language/docs/getting-started#set_up_your_project)
for your Google Cloud Platform project.

#### Questrade

Log in to your [Questrade](https://www.questrade.com/) account and
[enable the API + add an application](http://www.questrade.com/api/documentation/getting-started).
Then, fill in the QUESTRADE constants found [here](http://www.questrade.com/api/documentation/authorization) to environment variables:

```shell
export QUESTRADE_REFRESH_TOKEN="<YOUR_REFRESH_TOKEN>"
```

Also export your Questrade account number, which you'll find under
*[My Accounts](https://my.questrade.com/)*:

```shell
export QUESTRADE_ACCOUNT_NUMBER="<YOUR_ACCOUNT_NUMBER>"
```

### 3. Install dependencies

There are a few library dependencies, which you can install using
[pip](https://pip.pypa.io/en/stable/quickstart/):

```shell
$ pip install -r requirements.txt
```

### 4. Run the tests

Verify that everything is working as intended by running the tests with
[pytest](http://doc.pytest.org/en/latest/getting-started.html) using this
command:

```shell
$ export USE_REAL_MONEY=NO && pytest *.py --verbose
```

### 5. Run the benchmark

The [benchmark report](benchmark.md) shows how the current implementation of the
analysis and trading algorithms would have performed against historical data.
You can run it again to benchmark any changes you may have made:

```shell
$ ./benchmark.py > benchmark.md
```

### 6. Start the bot

Enable real orders that use your money:

```shell
$ export USE_REAL_MONEY=YES
```

Have the code start running in the background with this command:

```shell
$ nohup ./main.py &
```

##License

Copyright 2017 Max Braun

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
