// utils.js

// Helper math functions

async function loadHtml(path) {
  const response = await fetch(path);

  if (!response.ok) {
    throw new Error("Could not load HTML file: " + path);
  }

  return await response.text();
}

async function loadHtmlFiles(pathsByName) {
  const loaded = {};

  for (const name in pathsByName) {
    loaded[name] = await loadHtml(pathsByName[name]);
  }

  return loaded;
}


function getSurveyTextAnswer(data, questionName) {
  let responses = data.responses || data.response;

  if (typeof responses === "string") {
    responses = JSON.parse(responses);
  }
  if (responses && responses[questionName] !== undefined) {
    return responses[questionName];
  }
  if (responses && responses.Q0 !== undefined) {
    return responses.Q0;
  }
  return "";
}

function clampNumber(x, minValue, maxValue) {
  return Math.max(minValue, Math.min(maxValue, x));
}

function valueToPercent(value) {
  const clamped = clampNumber(value, MIN_AR_VALUE, MAX_AR_VALUE);
  return 100 * (clamped - MIN_AR_VALUE) / (MAX_AR_VALUE - MIN_AR_VALUE);
}

// Maximum points for one forecast. Keep in step with server/scoring.py.
const MAX_POINTS_PER_ROUND = 10;

function scoreForecast(forecast, actual) {
  const error = Math.abs(forecast - actual);
    // Afrouzi scoring rule
  return Math.round(MAX_POINTS_PER_ROUND * Math.max(0, (1 - (error / sd))));
}

// Mirrors compute_bonus() in server/scoring.py. The server recomputes the bonus
// from the recorded trials, so this is only what the participant is shown.
function computeBonusPayment(score) {
  const raw = EXPECTED_BONUS_DOLLARS * score / EXPECTED_SCORE_FOR_PAYMENT;
  return Math.min(Math.max(raw, 0), MAX_BONUS_DOLLARS);
}

function formatDollars(amount) {
  return "$" + amount.toFixed(2);
}

// Hide the survey-text submit button so the Return/Enter key is the only way to
// submit. The button stays in the form (visually hidden, out of the tab order)
// because the browser needs a submit button for Enter to submit the form.
function hideSurveyTextButton() {
  const button = document.querySelector("#jspsych-survey-text-next");

  if (!button) {
    return;
  }

  button.setAttribute("tabindex", "-1");
  button.setAttribute("aria-hidden", "true");
  button.style.cssText =
    "position:absolute;width:1px;height:1px;opacity:0;overflow:hidden;pointer-events:none;";
}

// Digits only. Length and exact-value checks are separate so the message can
// be the same red line under the box, shown only when Enter is pressed.
function restrictSurveyTextInputToDigits() {
  const inputs = document.querySelectorAll(
    ".jspsych-survey-text-question input, #jspsych-content input[type='text']"
  );

  inputs.forEach(function(input) {
    input.setAttribute("inputmode", "numeric");
    input.setAttribute("pattern", "[0-9]*");
    input.addEventListener("keydown", function(e) {
      const allowedKeys = [
        "Backspace",
        "Delete",
        "ArrowLeft",
        "ArrowRight",
        "Tab",
        "Enter",
        "Home",
        "End"
      ];

      if (allowedKeys.includes(e.key)) {
        return;
      }

      if (e.ctrlKey || e.metaKey) {
        return;
      }

      if (!/^[0-9]$/.test(e.key)) {
        e.preventDefault();
      }
    });

    input.addEventListener("input", function() {
      input.value = input.value.replace(/[^0-9]/g, "");
    });
  });
}

// On Enter, if `isInvalid(value)` is true, stay on the page and show `message`
// (a string, or a function of the typed value) in red under the box. The browser's own validation bubble is turned off.
function showErrorOnEnter(isInvalid, message) {
  const inputs = document.querySelectorAll(
    ".jspsych-survey-text-question input, #jspsych-content input[type='text']"
  );

  inputs.forEach(function(input) {
    let note = input.parentElement.querySelector(".ar-entry-error");
    if (!note) {
      note = document.createElement("p");
      note.className = "ar-entry-error";
      note.style.cssText = "color:#b00; margin-top:12px; min-height:1.2em; font-size:18px;";
      input.insertAdjacentElement("afterend", note);
    }

    input.addEventListener("input", function() {
      input.setCustomValidity("");
      note.textContent = "";
    });

    const form = input.form;
    if (!form || form.dataset.entryCheckBound === "1") {
      return;
    }
    form.dataset.entryCheckBound = "1";
    form.setAttribute("novalidate", "novalidate");
    form.addEventListener("submit", function(e) {
      if (!isInvalid(input.value.trim())) {
        return;
      }
      e.preventDefault();
      e.stopImmediatePropagation();
      note.textContent = typeof message === "function" ? message(input.value.trim()) : message;
    }, true);
  });
}

function requireExactShownValue(expected) {
  const target = String(expected);
  showErrorOnEnter(
    function(raw) { return raw !== target; },
    "That number is not valid. Please enter the number shown."
  );
}

function requireDigitCount(digits) {
  const pattern = new RegExp("^\\d{" + digits + "}$");
  showErrorOnEnter(
    function(raw) { return !pattern.test(raw); },
    "Enter a " + digits + "-digit number."
  );
}

// A forecast must be exactly `digits` digits and inside [min, max].
function requireForecastInRange(digits, min, max) {
  const pattern = new RegExp("^\\d{" + digits + "}$");
  showErrorOnEnter(
    function(raw) {
      return !pattern.test(raw) || Number(raw) < min || Number(raw) > max;
    },
    function(raw) {
      return pattern.test(raw)
        ? "Enter a number between " + min + " and " + max + "."
        : "Enter a " + digits + "-digit number.";
    }
  );
}


function applyForecastScoreOnce(roundIndex, forecast, actualValue) {
  const pointsEarned = scoreForecast(forecast, actualValue);

  if (scoredForecastRounds[roundIndex] === undefined) {
    cumulativeScore += pointsEarned;

    scoredForecastRounds[roundIndex] = {
      points_earned: pointsEarned,
      cumulative_score_after: cumulativeScore
    };
  }
  return scoredForecastRounds[roundIndex];
}

// Rendering functions

function surveyTextLayoutCss(options) {
  options = options || {};

  const minHeight = options.minHeight || "88vh";
  const inputWidth = options.inputWidth || "140px";
  const inputHeight = options.inputHeight || "30px";
  const inputFontSize = options.inputFontSize || "18px";
  const inputMarginTop = options.inputMarginTop || "20px";
  const buttonMarginTop = options.buttonMarginTop || "16px";
  const buttonFontSize = options.buttonFontSize || "16px";
  const buttonPadding = options.buttonPadding || "6px 14px";

  return `
    <style>
      #jspsych-content {
        width: 100%;
        min-height: ${minHeight};
        display: flex;
        align-items: center;
        justify-content: center;
        text-align: center;
      }

      #jspsych-survey-text-form {
        width: 100%;
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
      }

      .jspsych-survey-text-question {
        width: 100%;
        margin: 0 !important;
        display: flex;
        flex-direction: column;
        align-items: center;
      }

      .jspsych-survey-text-question p {
        width: 100%;
        margin: 0 !important;
      }

      .jspsych-survey-text-question input {
        display: block;
        width: ${inputWidth} !important;
        height: ${inputHeight} !important;
        font-size: ${inputFontSize} !important;
        text-align: center;
        margin: ${inputMarginTop} auto 0 auto !important;
        box-sizing: border-box;
      }

      #jspsych-survey-text-next {
        margin-top: ${buttonMarginTop} !important;
        font-size: ${buttonFontSize} !important;
        padding: ${buttonPadding} !important;
      }
    </style>
  `;
}

function buttonResponseLayoutCss(options) {
  options = options || {};

  const minHeight = options.minHeight || "88vh";
  const buttonMarginTop = options.buttonMarginTop || "28px";
  const buttonFontSize = options.buttonFontSize || "18px";
  const buttonPadding = options.buttonPadding || "7px 18px";

  return `
    <style>
      #jspsych-content {
        width: 100%;
        min-height: ${minHeight};
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        text-align: center;
      }

      #jspsych-html-button-response-stimulus {
        text-align: center;
      }

      #jspsych-html-button-response-btngroup {
        margin-top: ${buttonMarginTop} !important;
        text-align: center;
      }

      .jspsych-html-button-response-button {
        margin: 0 8px !important;
      }

      .jspsych-html-button-response-button button {
        font-size: ${buttonFontSize} !important;
        padding: ${buttonPadding} !important;
      }
    </style>
  `;
}

function renderInformationalPage(html) {
  return `
    ${buttonResponseLayoutCss({
      minHeight: "88vh",
      buttonMarginTop: "24px",
      buttonFontSize: "18px",
      buttonPadding: "7px 18px"
    })}

    <div style="
      max-width: 750px;
      width: 100%;
      margin: 0 auto;
      text-align: center;
      font-size: 22px;
      line-height: 1.4;
    ">
      ${html}
    </div>
  `;
}

function renderCenteredValueScreen(options) {
  const actualValue = options.actualValue;
  const forecastValue = options.forecastValue;
  const showForecast = options.showForecast === true;
  const showScore = options.showScore === true;
  const size = options.size || "large";

  const actualPct = valueToPercent(actualValue, MIN_AR_VALUE, MAX_AR_VALUE);

  const isCompact = size === "compact";

  const numberFontSize = isCompact ? "42px" : "50px";
  const barWidth = isCompact ? "900px" : "1100px";
  const barHeight = isCompact ? "54px" : "72px";
  const fillHeight = isCompact ? "54px" : "72px";
  const dotSize = isCompact ? "44px" : "54px";
  const instructionFontSize = isCompact ? "18px" : "20px";

  const inputWidth = isCompact ? "100px" : "140px";
  const inputHeight = isCompact ? "30px" : "34px";
  const inputFontSize = isCompact ? "18px" : "20px";

  let forecastMarkerHtml = "";

  if (
    showForecast &&
    forecastValue !== null &&
    forecastValue !== undefined &&
    !isNaN(Number(forecastValue))
  ) {
    const forecastPct = valueToPercent(Number(forecastValue));
    const lineWidth = isCompact ? "3px" : "5px";

    forecastMarkerHtml = `
      <div style="
        position: absolute;
        left: ${forecastPct}%;
        top: -8px;
        width: ${lineWidth};
        height: calc(${barHeight} + 16px);
        background: #d83b3b;
        border-radius: 4px;
        transform: translateX(-50%);
        z-index: 5;
      "></div>
    `;
  }

  let rulerTicksHtml = "";

  // 20 ticks across the bar (as before), every second one tall.
  const TICK_COUNT = 20;
  const tickStep = (MAX_AR_VALUE - MIN_AR_VALUE) / TICK_COUNT;

  for (let tickIndex = 1; tickIndex <= TICK_COUNT; tickIndex++) {
    const tickValue = MIN_AR_VALUE + tickIndex * tickStep;
    const tickPct = valueToPercent(tickValue);
    const isMajorTick = tickIndex % 2 === 0;

    rulerTicksHtml += `
      <div style="
        position: absolute;
        left: ${tickPct}%;
        bottom: 0;
        width: 2px;
        height: ${isMajorTick ? "100%" : "55%"};
        background: #333333;
        transform: translateX(-50%);
        z-index: 4;
      "></div>
    `;
  }

  return `
    ${showScore ? renderScoreBox(cumulativeScore) : ""}

    ${surveyTextLayoutCss({
      minHeight: "88vh",
      inputWidth: inputWidth,
      inputHeight: inputHeight,
      inputFontSize: inputFontSize,
      inputMarginTop: "20px",
      buttonMarginTop: "16px"
    })}

    <div style="
      width: 100%;
      display: flex;
      flex-direction: column;
      align-items: center;
      text-align: center;
    ">

      <div style="
        font-size: ${numberFontSize};
        line-height: 1;
        margin-bottom: 28px;
        font-family: Arial, sans-serif;
        font-weight: normal;
      ">
        ${actualValue}
      </div>

      <div style="
        position: relative;
        width: ${barWidth};
        max-width: 92vw;
        height: ${barHeight};
        margin: 0 auto 30px auto;
        background: #eeeeee;
        overflow: hidden;
      ">

      <div style="
        position: absolute;
        left: 0;
        top: 0;
        width: ${actualPct}%;
        height: 100%;
        background: #6aa6dd;
        box-sizing: border-box;
        z-index: 2;
      "></div>

      ${rulerTicksHtml}

      ${forecastMarkerHtml}
    </div>

      <div style="
        font-size: ${instructionFontSize};
        font-family: Arial, sans-serif;
        margin-bottom: 0;
      ">
        Type the value shown above, then press Enter.
      </div>

    </div>
  `;
}

function renderForecastEntryPrompt() {
  return `
    ${surveyTextLayoutCss({
      minHeight: "88vh",
      inputWidth: "140px",
      inputHeight: "30px",
      inputFontSize: "18px",
      inputMarginTop: "20px",
      buttonMarginTop: "16px"
    })}

    <div style="
      font-size: 24px;
      font-family: Arial, sans-serif;
      text-align: center;
    ">
      Forecast the next value of the process, then press Enter.
    </div>
  `;
}


function renderScoreBox() {
  return `
    <div style="
      position: fixed;
      right: 24px;
      bottom: 20px;
      padding: 10px 14px;
      border: 1px solid #999;
      border-radius: 8px;
      background: #f7f7f7;
      font-size: 18px;
      z-index: 9999;
    ">
      Score: <strong>${cumulativeScore}</strong>
    </div>
  `;
}

function renderObservationValueDisplay(actualValue) {
  return renderCenteredValueScreen({
    actualValue: actualValue,
    showForecast: false,
    showScore: false,
    size: "large"
  });
}

function renderForecastFeedback(actualValue, forecastValue, pointsEarned) {
  return renderCenteredValueScreen({
    actualValue: actualValue,
    forecastValue: forecastValue,
    showForecast: true,
    showScore: true,
    size: "large"
  });
}


function renderStatusPage(heading, detailHtml) {
  return `
    <div style="
      text-align: center;
      margin: 160px auto 0 auto;
      max-width: 700px;
      font-size: 22px;
      line-height: 1.5;
      font-family: Arial, sans-serif;
    ">
      <h2>${heading}</h2>
      <p>${detailHtml || ""}</p>
    </div>
  `;
}

function renderFatalError(heading, detailHtml, contactAddress) {
  return `
    <div style="
      text-align: center;
      margin: 120px auto 0 auto;
      max-width: 700px;
      font-size: 20px;
      line-height: 1.5;
      font-family: Arial, sans-serif;
    ">
      <h2>${heading}</h2>
      <p>${detailHtml || ""}</p>
      <p style="margin-top: 28px; font-size: 17px;">
        If you need help, contact
        <a href="mailto:${contactAddress}">${contactAddress}</a>.
      </p>
    </div>
  `;
}


function showFullscreenWarning() {
  if (document.querySelector("#fullscreen-warning-overlay")) {
    return;
  }

  const overlay = document.createElement("div");
  overlay.id = "fullscreen-warning-overlay";

  overlay.innerHTML = `
    <div style="
      position: fixed;
      left: 0;
      top: 0;
      width: 100vw;
      height: 100vh;
      background: rgba(255, 255, 255, 0.96);
      z-index: 999999;
      display: flex;
      align-items: center;
      justify-content: center;
      text-align: center;
      font-family: Arial, sans-serif;
    ">
      <div style="
        max-width: 700px;
        padding: 36px;
        border: 3px solid #b00020;
        background: #ffffff;
      ">
        <div style="
          font-size: 54px;
          margin-bottom: 16px;
        ">
          ⚠️
        </div>

        <h2 style="margin-top: 0;">
          Fullscreen Required
        </h2>

        <p style="
          font-size: 20px;
          line-height: 1.45;
        ">
          You have exited fullscreen mode. Please return to fullscreen to continue the experiment.
        </p>

        <button id="return-fullscreen-button" style="
          margin-top: 20px;
          font-size: 18px;
          padding: 8px 22px;
        ">
          Return to fullscreen
        </button>
      </div>
    </div>
  `;

  document.body.appendChild(overlay);

  document
    .querySelector("#return-fullscreen-button")
    .addEventListener("click", function() {
      document.documentElement.requestFullscreen();
    });
}


document.addEventListener("fullscreenchange", function() {
  const isFullscreen = document.fullscreenElement !== null;

  if (isFullscreen) {
    const overlay = document.querySelector("#fullscreen-warning-overlay");

    if (overlay) {
      overlay.remove();
    }

    intentionalFullscreenExit = false;
    return;
  }

  if (fullscreenMonitoringActive && !intentionalFullscreenExit) {
    fullscreenExitCount += 1;
    showFullscreenWarning();
  }
});
