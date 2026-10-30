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
const MAX_POINTS_PER_ROUND = 100;

function scoreForecast(forecast, actual) {
  const error = Math.abs(forecast - actual);
    // Afrouzi scoring rule
  return Math.round(MAX_POINTS_PER_ROUND * Math.max(0, (1 - (error / sd))));
}

// Mirrors compute_bonus() in server/scoring.py. The server recomputes the bonus
// from the recorded trials, so this is only what the participant is shown.
function computeBonusPayment(score) {
  const raw = EXPECTED_BONUS_DOLLARS * score / EXPECTED_SCORE_FOR_PAYMENT;
  return Math.max(raw, 0);
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
const MAX_ENTRY_DIGITS = 3;

// The red line under an entry box (created on first use).
function getEntryErrorNote(input) {
  const anchor = input.closest(".digit-entry") || input;
  let note = anchor.parentElement.querySelector(".ar-entry-error");
  if (!note) {
    note = document.createElement("p");
    note.className = "ar-entry-error";
    // Fixed height: the line is reserved while empty, so showing a message
    // never moves anything else on the page.
    note.style.cssText = "color:#b00; margin-top:12px; height:28px; line-height:28px; overflow:hidden; font-size:18px;";
    anchor.insertAdjacentElement("afterend", note);
  }
  return note;
}

// Three square boxes, one digit each, drawn over the real text input. The input
// stays in place (invisible, stretched over the boxes) so typing, the digit
// limit, validation and submitting work exactly as with a plain box; the boxes
// just mirror what it holds.
const DIGIT_BOX_CSS = `
  .digit-entry {
    position: relative;
    display: flex;
    gap: 7px;
    width: max-content;
    margin: 20px auto 0 auto;
  }
  .digit-cell {
    box-sizing: border-box;
    width: 94px;
    height: 94px;
    border: 2px solid #aaaaaa;
    border-radius: 8px;
    background: #ffffff;
    color: #111111;
    font-family: Arial, sans-serif;
    font-size: 52px;
    line-height: 1;
    display: flex;
    align-items: center;
    justify-content: center;
  }
  .digit-cell.active {
    border-color: #e0a030;
    box-shadow: 0 0 0 3px rgba(224, 160, 48, 0.3);
  }
  .jspsych-survey-text-question .digit-entry > input.digit-input {
    position: absolute !important;
    top: 0;
    left: 0;
    width: 100% !important;
    height: 100% !important;
    margin: 0 !important;
    padding: 0;
    border: 0;
    opacity: 0;
    cursor: text;
  }
`;

function makeDigitBoxes(input) {
  if (input.closest(".digit-entry")) {
    return;
  }
  if (!document.getElementById("digit-entry-style")) {
    const style = document.createElement("style");
    style.id = "digit-entry-style";
    style.textContent = DIGIT_BOX_CSS;
    document.head.appendChild(style);
  }

  const wrap = document.createElement("div");
  wrap.className = "digit-entry";
  input.insertAdjacentElement("beforebegin", wrap);

  const cells = [];
  for (let i = 0; i < MAX_ENTRY_DIGITS; i++) {
    const cell = document.createElement("div");
    cell.className = "digit-cell";
    wrap.appendChild(cell);
    cells.push(cell);
  }
  wrap.appendChild(input);
  input.classList.add("digit-input");

  function refresh() {
    const value = input.value;
    const focused = document.activeElement === input;
    cells.forEach(function(cell, i) {
      cell.textContent = value.charAt(i);
      cell.classList.toggle("active", focused && i === Math.min(value.length, MAX_ENTRY_DIGITS - 1));
    });
  }
  ["input", "focus", "blur"].forEach(function(name) {
    input.addEventListener(name, refresh);
  });

  // Reserve the message line under the boxes from the start.
  getEntryErrorNote(input);

  // Moving the input drops the focus jsPsych gave it.
  input.focus();
  refresh();
}

// The "too many digits" message fades after a moment (a message from pressing
// Enter stays until the next edit).
const TOO_MANY_DIGITS_NOTE_MS = 1500;
let tooManyDigitsTimer = null;

function showTooManyDigitsNote(input) {
  const note = getEntryErrorNote(input);
  const text = "Enter a " + MAX_ENTRY_DIGITS + "-digit number.";
  note.textContent = text;
  clearTimeout(tooManyDigitsTimer);
  tooManyDigitsTimer = setTimeout(function() {
    if (note.textContent === text) {
      note.textContent = "";
    }
  }, TOO_MANY_DIGITS_NOTE_MS);
}

function restrictSurveyTextInputToDigits() {
  const inputs = document.querySelectorAll(
    ".jspsych-survey-text-question input, #jspsych-content input[type='text']"
  );

  inputs.forEach(function(input) {
    input.setAttribute("inputmode", "numeric");
    input.setAttribute("pattern", "[0-9]*");
    input.setAttribute("maxlength", String(MAX_ENTRY_DIGITS));
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

    // The box holds at most 3 digits: anything that would make it longer (typed,
    // pasted, or from an on-screen keyboard) is not entered and the message is
    // shown. It clears on the next edit.
    input.addEventListener("beforeinput", function(e) {
      if (!e.inputType || e.inputType.indexOf("insert") !== 0) {
        return;
      }
      const inserted = e.data !== null && e.data !== undefined
        ? e.data
        : (e.dataTransfer ? e.dataTransfer.getData("text") : "");
      const digits = inserted.replace(/[^0-9]/g, "");
      if (!digits) {
        return;
      }
      const replacing = input.selectionEnd - input.selectionStart;
      if (input.value.length - replacing + digits.length > MAX_ENTRY_DIGITS) {
        e.preventDefault();
        showTooManyDigitsNote(input);
      }
    });

    input.addEventListener("input", function() {
      input.value = input.value.replace(/[^0-9]/g, "");
      clearTimeout(tooManyDigitsTimer);
    });

    makeDigitBoxes(input);
  });
}

// On Enter, if `isInvalid(value)` is true, stay on the page and show `message`
// (a string, or a function of the typed value) in red under the box. The browser's own validation bubble is turned off.
function showErrorOnEnter(isInvalid, message) {
  const inputs = document.querySelectorAll(
    ".jspsych-survey-text-question input, #jspsych-content input[type='text']"
  );

  inputs.forEach(function(input) {
    const note = getEntryErrorNote(input);

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

// Centre a marker on its position, except at the bar's ends where it is kept
// inside the bar (the bar clips anything that sticks out).
function edgeShift(pct) {
  if (pct <= 0) {
    return "translateX(0)";
  }
  if (pct >= 100) {
    return "translateX(-100%)";
  }
  return "translateX(-50%)";
}

function renderCenteredValueScreen(options) {
  const actualValue = options.actualValue;
  const forecastValue = options.forecastValue;
  const showForecast = options.showForecast === true;
  const showScore = options.showScore === true;
  const size = options.size || "large";
  const hasValue = actualValue !== null && actualValue !== undefined;
  const instruction = options.instruction || "Type the value shown above, then press Enter.";
  const fillIdAttr = options.fillId ? `id="${options.fillId}"` : "";

  const actualPct = hasValue ? valueToPercent(actualValue) : 0;

  const isCompact = size === "compact";

  const numberFontSize = isCompact ? "42px" : "65px";
  const barWidth = isCompact ? "900px" : "1100px";
  const barHeight = isCompact ? "54px" : "90px";
  const fillHeight = isCompact ? "54px" : "90px";
  const dotSize = isCompact ? "44px" : "54px";
  const instructionFontSize = isCompact ? "18px" : "26px";

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
        transform: ${edgeShift(forecastPct)};
        z-index: 5;
      "></div>
    `;
  }

  let rulerTicksHtml = "";
  let rulerLabelsHtml = "";

  // 21 ticks from MIN to MAX (one every 10 units), every fifth one tall. The
  // end ticks sit inside the bar so they are not clipped.
  const TICK_COUNT = 20;
  const tickStep = (MAX_AR_VALUE - MIN_AR_VALUE) / TICK_COUNT;
  const LABEL_EVERY = 5;

  for (let tickIndex = 0; tickIndex <= TICK_COUNT; tickIndex++) {
    const tickValue = MIN_AR_VALUE + tickIndex * tickStep;
    const tickPct = valueToPercent(tickValue);
    const isMajorTick = tickIndex % 5 === 0;

    rulerTicksHtml += `
      <div style="
        position: absolute;
        left: ${tickPct}%;
        bottom: 0;
        width: 2px;
        height: ${isMajorTick ? "100%" : "32%"};
        background: #333333;
        transform: ${edgeShift(tickPct)};
        z-index: 4;
      "></div>
    `;

    if (tickIndex % LABEL_EVERY === 0) {
      rulerLabelsHtml += `
        <div style="
          position: absolute;
          left: ${tickPct}%;
          top: 6px;
          transform: translateX(-50%);
          font-size: 18px;
          line-height: 1;
          color: #333333;
          font-family: Arial, sans-serif;
        ">${tickValue}</div>
      `;
    }
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
        ${hasValue ? actualValue : "&nbsp;"}
      </div>

      <div style="
        position: relative;
        width: ${barWidth};
        max-width: 92vw;
        margin: 0 auto 52px auto;
      ">
        <div style="
          position: relative;
          width: 100%;
          height: ${barHeight};
          background: #eeeeee;
          overflow: hidden;
        ">

          <div ${fillIdAttr} style="
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

        <div style="position: absolute; left: 0; top: ${barHeight}; width: 100%;">
          ${rulerLabelsHtml}
        </div>
      </div>

      <div style="
        font-size: ${instructionFontSize};
        font-family: Arial, sans-serif;
        margin-bottom: 0;
      ">
        ${instruction}
      </div>

    </div>
  `;
}

// Same layout as the other screens, with an empty (gray) bar and no number.
// bindForecastBar() fills it once a valid forecast has been typed.
function renderForecastEntryPrompt() {
  return renderCenteredValueScreen({
    actualValue: null,
    showForecast: false,
    showScore: false,
    size: "large",
    instruction: "Forecast the next value of the process, then press Enter.",
    fillId: "forecast-bar-fill"
  });
}

// Show the typed forecast on the bar as soon as it is a valid 3-digit value
// in range; otherwise the bar stays gray.
function bindForecastBar(digits, min, max) {
  const fill = document.getElementById("forecast-bar-fill");
  const input = document.querySelector(
    ".jspsych-survey-text-question input, #jspsych-content input[type='text']"
  );
  if (!fill || !input) {
    return;
  }
  const pattern = new RegExp("^\\d{" + digits + "}$");
  input.addEventListener("input", function() {
    const raw = input.value.trim();
    const valid = pattern.test(raw) && Number(raw) >= min && Number(raw) <= max;
    fill.style.width = valid ? valueToPercent(Number(raw)) + "%" : "0%";
  });
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


// Debug sessions only: append where we are in the experiment (for example
// "Forecast 37 / 250") to the debug banner in the bottom-left corner.
function updateDebugProgress(text) {
  const el = document.getElementById("debug-progress");
  if (el) {
    el.textContent = " \u2014 " + text;
  }
}
