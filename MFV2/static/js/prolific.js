// prolific.js
//
// Replaces the psiTurk client library. Provides the same three things task.js
// needs -- record a trial, save the data, finish the session -- but talks to
// this project's own /api routes and returns participants to Prolific rather
// than submitting an MTurk HIT.
//
// Data is flushed to the server during the task instead of only at the end, so
// a participant who closes the tab still leaves the trials they finished.

(function () {
  "use strict";

  const FLUSH_EVERY_N_TRIALS = 10;
  const FLUSH_INTERVAL_MS = 15000;
  const MAX_RETRIES = 4;
  const RETRY_BASE_DELAY_MS = 1000;

  function ExperimentClient(config) {
    this.config = config;
    this.uniqueId = config.uniqueId;

    // Trials recorded but not yet acknowledged by the server.
    this.pending = [];
    // Everything recorded this session, kept so the final POST can resend if a
    // mid-task flush was lost.
    this.all = [];

    this.flushing = false;
    this.finished = false;

    const self = this;
    this.flushTimer = setInterval(function () {
      self.flush();
    }, FLUSH_INTERVAL_MS);

    // Best-effort save if the participant closes the tab mid-task.
    window.addEventListener("pagehide", function () {
      self.beacon();
    });
    document.addEventListener("visibilitychange", function () {
      if (document.visibilityState === "hidden") {
        self.beacon();
      }
    });
  }

  ExperimentClient.prototype.recordTrialData = function (trial) {
    this.pending.push(trial);
    this.all.push(trial);

    if (this.pending.length >= FLUSH_EVERY_N_TRIALS) {
      this.flush();
    }
  };

  ExperimentClient.prototype.post = async function (url, payload, retries) {
    if (retries === undefined) {
      retries = MAX_RETRIES;
    }

    for (let attempt = 0; attempt <= retries; attempt++) {
      try {
        const response = await fetch(url, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
          keepalive: true
        });

        if (response.ok) {
          return await response.json();
        }

        // 4xx means the request itself is wrong; retrying will not help.
        if (response.status >= 400 && response.status < 500) {
          throw new Error("Server rejected the request: " + response.status);
        }
      } catch (error) {
        if (attempt === retries) {
          throw error;
        }
      }

      await new Promise(function (resolve) {
        setTimeout(resolve, RETRY_BASE_DELAY_MS * Math.pow(2, attempt));
      });
    }

    throw new Error("Could not reach the server after " + (retries + 1) + " attempts");
  };

  ExperimentClient.prototype.flush = async function () {
    if (this.flushing || this.finished || this.pending.length === 0) {
      return;
    }

    this.flushing = true;
    const batch = this.pending;
    this.pending = [];

    try {
      await this.post(this.config.dataUrl, {
        uniqueId: this.uniqueId,
        trials: batch
      });
    } catch (error) {
      console.error("Could not save trial data, will retry with the next flush:", error);
      // Put the batch back at the front of the queue.
      this.pending = batch.concat(this.pending);
    } finally {
      this.flushing = false;
    }
  };

  // sendBeacon survives the page unloading, unlike fetch.
  ExperimentClient.prototype.beacon = function () {
    if (this.finished || this.pending.length === 0 || !navigator.sendBeacon) {
      return;
    }

    const payload = JSON.stringify({
      uniqueId: this.uniqueId,
      trials: this.pending
    });

    const sent = navigator.sendBeacon(
      this.config.dataUrl,
      new Blob([payload], { type: "application/json" })
    );

    if (sent) {
      this.pending = [];
    }
  };

  /**
   * Finish the session. Recomputes nothing client-side -- the server scores the
   * recorded trials and hands back the Prolific submission URL.
   */
  ExperimentClient.prototype.complete = async function (summary) {
    clearInterval(this.flushTimer);

    // Send anything still queued along with the completion request so the
    // server has the full record before it scores.
    const trailing = this.pending;
    this.pending = [];

    const result = await this.post(
      this.config.completeUrl,
      {
        uniqueId: this.uniqueId,
        trials: trailing,
        score: summary.score,
        failedCompetency: summary.failedCompetency === true,
        feedback: summary.feedback || null,
        fullscreenExitCount: summary.fullscreenExitCount || 0
      },
      MAX_RETRIES
    );

    this.finished = true;
    return result;
  };

  ExperimentClient.prototype.returnToProlific = function (result) {
    const url = result && result.completionUrl;

    if (url) {
      window.location.replace(url);
      return true;
    }

    return false;
  };

  window.ExperimentClient = ExperimentClient;
})();
