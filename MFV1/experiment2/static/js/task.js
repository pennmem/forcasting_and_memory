// task.js

let failedCompetency = false;
let failureScreenShown = false;

// Questions 1 and 3 are the ones that count toward exclusion. A participant is
// only screened out if they miss BOTH -- missing just one is fine. failedCompetency
// (above) is derived from these two once question 3 has been answered.
let failedQ1 = false;
let failedQ3 = false;

let fullscreenMonitoringActive = false;
let fullscreenExitCount = 0;
let intentionalFullscreenExit = false;

let cumulativeScore = 0;
let latestForecast = null;
let scoredForecastRounds = {};
let participantFeedback = null;

// Every parameter below comes from config.ini and is injected into the page by
// the server, so what the participant is told they will earn and what the
// server actually pays are computed from the same numbers. Change them in
// config.ini, not here.
const CONFIG = window.TASK_CONFIG;

const sd = CONFIG.score_sd;
const MIN_AR_VALUE = CONFIG.min_ar_value;
const MAX_AR_VALUE = CONFIG.max_ar_value;

const FLAT_FEE_DOLLARS = CONFIG.flat_fee_dollars;
const EXPECTED_BONUS_DOLLARS = CONFIG.expected_bonus_dollars;
const EXPECTED_SCORE_FOR_PAYMENT = CONFIG.expected_score_for_payment;
const MAX_BONUS_DOLLARS = CONFIG.max_bonus_dollars;

const FORECAST_START_INDEX = CONFIG.forecast_start_index;
const MAX_TRIALS = CONFIG.max_trials;
const DISTRACTOR_LENGTH = CONFIG.distractor_length_ms;

// Identifiers for this session, assigned by the server.
const uniqueId = CONFIG.uniqueId;
const condition = CONFIG.condition;
const counterbalance = CONFIG.counterbalance;
const codeversion = CONFIG.codeversion;
const contact_address = CONFIG.contactAddress;

const experiment = new ExperimentClient(CONFIG);

async function loadAssignment() {
  const response = await fetch(CONFIG.assignmentsUrl);

  if (!response.ok) {
    throw new Error("Could not load assignments.json");
  }

  const data = await response.json();
  const slot = Number(counterbalance);
  const assignment = data.assignments[slot];

  if (!assignment) {
    throw new Error("No assignment found for counterbalance slot: " + slot);
  }

  return assignment;
}

function buildEnterFullscreenTrial() {
  return {
    type: "fullscreen",
    fullscreen_mode: true,
    message: renderInformationalPage(`
      <h2>Fullscreen Required</h2>
      <p>
        The experiment must be completed in fullscreen mode. <br>
        Please click the button below to enter fullscreen and begin the experiment.
      </p>
    `),
    button_label: "Enter fullscreen",
    data: {
      phase: "enter_fullscreen"
    },
    on_finish: function(data) {
      fullscreenMonitoringActive = true;
      intentionalFullscreenExit = false;
      data.fullscreen_monitoring_active = true;
    }
  };
}

function buildExitFullscreenTrial(reason) {
  return {
    type: "fullscreen",
    fullscreen_mode: false,
    delay_after: 0,
    data: {
      phase: "exit_fullscreen",
      fullscreen_exit_reason: reason
    },
    on_start: function() {
      fullscreenMonitoringActive = false;
      intentionalFullscreenExit = true;
    }
  };
}

function buildCompetencyFailureNode(failureHtml) {
  return {
    timeline: [
      buildCompetencyFailureTrial(failureHtml),
      buildExitFullscreenTrial("competency_failure")
    ],
    conditional_function: function() {
      return failedCompetency && !failureScreenShown;
    }
  };
}


function buildCompetencyCheck(html) {
  const timeline = [];

  timeline.push({
    type: "html-button-response",
    stimulus: renderInformationalPage(html.competency_intro),
    choices: ["Continue"],
    data: {
      phase: "competency_intro"
    }
  });

  // Question 1: matters, but only in combination with question 3 -- see below.
  timeline.push({
    type: "html-button-response",
    stimulus: renderInformationalPage(html.competency_q1),
    choices: ['Blue', 'Orange'],
    data: {
      phase: "competency_check",
      competency_question_number: 1,
      competency_matters_for_exclusion: true,
      correct_response: 0 // Blue is correct.
    },
    on_finish: function(data) {
      data.competency_response = data.response;
      data.competency_correct = data.response === 0;

      failedQ1 = !data.competency_correct;

      // Exclusion is not decided until question 3 has also been answered.
      data.failed_competency = failedCompetency;
    }
  });

  // Question 2: does NOT matter
  timeline.push({
    type: "html-button-response",
    stimulus: renderInformationalPage(html.competency_q2),
    choices: ["<5 years", "5-15 years", "15-25 years", "25+ years"],
    data: {
      phase: "competency_check",
      competency_question_number: 2,
      competency_matters_for_exclusion: false,
      correct_response: 0
    },
    on_finish: function(data) {
      data.competency_response = data.response;
      data.competency_correct = data.response === 0;

      // Important: question 2 is recorded, but does not change failedCompetency.
      data.failed_competency = failedCompetency;
    }
  });

  // Question 3: matters, but only in combination with question 1. A participant
  // is screened out only if they missed BOTH question 1 and question 3 --
  // missing just one is not disqualifying.
  timeline.push({
    type: "html-button-response",
    stimulus: renderInformationalPage(html.competency_q3),
    choices: ["Never", "Daily", "Weekly", "Monthly"],
    data: {
      phase: "competency_check",
      competency_question_number: 3,
      competency_matters_for_exclusion: true,
      correct_response: 0 // Never is correct.
    },
    on_finish: function(data) {
      data.competency_response = data.response;
      data.competency_correct = data.response === 0;

      failedQ3 = !data.competency_correct;
      failedCompetency = failedQ1 && failedQ3;

      data.failed_competency = failedCompetency;
    }
  });

  // Failure screen, shown only if both question 1 and question 3 were missed.
  timeline.push(buildCompetencyFailureNode(html.competency_failure));

  return timeline;
}

function buildCompetencyFailureTrial(failureHtml) {
  return {
    type: "html-button-response",
    stimulus: renderInformationalPage(failureHtml),
    choices: ["Exit"],
    data: {
      phase: "competency_failed"
    },
    on_finish: function(data) {
      failureScreenShown = true;
      data.failure_screen_shown = true;
    }
  };
}

function buildInstructions(
  instructions1Html,
  instructions2Html,
  instructions3Html,
  instructions4Html
) {
  let instructionPage = 0;
  let finishedInstructions = false;

  const pages = [
    {
      html: instructions1Html,
      phase: "instructions_1",
      choices: ["Read Instructions"]
    },
    {
      html: instructions2Html,
      phase: "instructions_2",
      choices: ["Next"]
    },
    {
      html: instructions3Html,
      phase: "instructions_3",
      choices: ["Previous", "Next"]
    },
    {
      html: instructions4Html,
      phase: "instructions_4",
      choices: ["Previous", "Begin Experiment"]
    }
  ];

  const instructionTrial = {
    type: "html-button-response",

    stimulus: function() {
      return renderInformationalPage(pages[instructionPage].html);
    },

    choices: function() {
      return pages[instructionPage].choices;
    },

    data: {
      phase: "instructions"
    },

    on_finish: function(data) {
      const pageShown = instructionPage;
      const response = data.response;

      data.instruction_page_number = pageShown + 1;
      data.instruction_phase = pages[pageShown].phase;

      // Page 1: only Next
      if (pageShown === 0) {
        instructionPage = 1;
      }

      // Page 2: Previous or Next
      else if (pageShown === 1) {
          instructionPage = 2;

      }

      // Page 3: Previous or Next
      else if (pageShown === 2) {
        if (response === 0) {
          instructionPage = 1;
        } else {
          instructionPage = 3;
        }
      }

      // Page 4: Begin Experiment
     else if (pageShown === 3) {
        if (response === 0) {
          instructionPage = 2;
        } else {
          finishedInstructions = true;
        }
      }

      data.next_instruction_page = instructionPage + 1;
      data.finished_instructions = finishedInstructions;
    }
  };

  return [
    {
      timeline: [instructionTrial],
      loop_function: function() {
        return !finishedInstructions;
      }
    }
  ];
}

function buildDistractorQuestion(taskType, word, roundIndex, taskNumber, wordIndex) {
  let questionText;

  if (taskType === "animacy") {
    questionText = "Does this item refer to something living?";
  } else if (taskType === "size") {
    questionText = "Will this item fit in a shoebox?";
  } else {
    throw new Error("Unknown task type: " + taskType);
  }

  return {
    type: "html-button-response",
    stimulus: `
      ${buttonResponseLayoutCss({
        minHeight: "88vh",
        buttonMarginTop: "28px",
        buttonFontSize: "20px",
        buttonPadding: "8px 22px"
      })}

      <div style="
        text-align: center;
      ">
        <div style="
          font-size: 42px;
          font-weight: bold;
          margin-bottom: 18px;
        ">
          ${word}
        </div>

        <div style="
          font-size: 30px;
        ">
          ${questionText}
        </div>
      </div>
    `,
    choices: ["Yes", "No"],
    response_ends_trial: true,
    data: {
      phase: "distractor_question",
      round_index: roundIndex,
      task_number: taskNumber,
      task_type: taskType,
      word: word,
      word_index: wordIndex
    }
  };
}

function buildDistractorBlock(roundIndex, distractionTask) {
  const taskType = distractionTask.task_type;
  const words = distractionTask.words;

  let blockStartTime = null;

  const conditionalTrials = words.map(function(word, wordIndex) {
    const trial = buildDistractorQuestion(
      taskType,
      word,
      roundIndex,
      distractionTask.task_number,
      wordIndex
    );

    // The current question should stay on screen until the participant answers.
    trial.on_finish = function(data) {
      const elapsed = performance.now() - blockStartTime;

      data.distractor_block_elapsed_ms = elapsed;
      data.distractor_block_time_limit_ms = DISTRACTOR_LENGTH;
      data.distractor_finished_after_time_limit = elapsed >= DISTRACTOR_LENGTH;

      data.distractor_response_index = data.response;

      if (data.response === 0) {
        data.distractor_response = "yes";
      } else if (data.response === 1) {
        data.distractor_response = "no";
      } else {
        data.distractor_response = "no_answer";
      }

      data.distractor_answered = data.response === 0 || data.response === 1;

      if (data.response === 0 || data.response === 1) {
        data.distractor_response_time_ms = data.rt;
      } else {
        data.distractor_response_time_ms = null;
      }

    };

    return {
      timeline: [trial],
      conditional_function: function() {
        const now = performance.now();

        if (blockStartTime === null) {
          blockStartTime = now;
        }
        const elapsed = now - blockStartTime;

        return elapsed < DISTRACTOR_LENGTH;
      }
    };
  });

  return {
    timeline: conditionalTrials,
    data: {
      phase: "distractor_block",
      round_index: roundIndex,
      task_type: taskType
    }
  };
}

function buildValueRecallTrial(roundIndex, value) {
  return {
    type: "survey-text",
    questions: [
      {
        prompt: `
          ${renderObservationValueDisplay(value)}
        `,
        name: "typed_value",
        required: true
      }
    ],
    on_load: function() {
  restrictSurveyTextInputToDigits();

  if (roundIndex === FORECAST_START_INDEX - 1) {
    buildTransitionScreen(`
      This is the end of the observation phase. 
      Next, you will begin forecasting future values.
    `);
  }
},
    data: {
      phase: "ar1_value_entry",
      round_index: roundIndex,
      true_value: value
    },
    on_finish: function(data) {
      let responses = data.responses || data.response;

      if (typeof responses === "string") {
        responses = JSON.parse(responses);
      }

      let typed;

      if (responses && responses.typed_value !== undefined) {
        typed = responses.typed_value;
      } else if (responses && responses.Q0 !== undefined) {
        typed = responses.Q0;
      } else {
        typed = "";
        console.warn("Could not find typed response in trial data:", data);
      }

      data.typed_value = typed;
      data.correct = String(typed).trim() === String(value);
    }
  };
}

function buildValueRecallLoop(roundIndex, value) {
  return {
    timeline: [
      buildValueRecallTrial(roundIndex, value)
    ],
    loop_function: function(data) {
      const lastTrial = data.values()[0];

      // Repeat the passive recall screen until they type the correct value.
      return !lastTrial.correct;
    }
  };
}

function buildTransitionScreen(html) {
  const button = document.querySelector("#jspsych-survey-text-next");

  if (!button) {
    return;
  }

  button.insertAdjacentHTML("afterend", `
    <div style="
      margin-top: 24px;
      max-width: 700px;
      text-align: center;
      font-size: 18px;
      line-height: 1.4;
      font-family: Arial, sans-serif;
    ">
      ${html}
    </div>
  `);
}

function buildForecastTrial(roundIndex, previousValue) {
  return {
    type: "survey-text",
    questions: [{
      prompt: renderForecastEntryPrompt(),
      name: "forecast_value",
      required: true
    }],
    on_load: function() {
      restrictSurveyTextInputToDigits();
    },
    data: {
      phase: "forecast",
      round_index: roundIndex,
      previous_value: previousValue
    },
    on_finish: function(data) {
      const typed = getSurveyTextAnswer(data, "forecast_value");
      const forecast = Number(String(typed).trim());

      latestForecast = forecast;

      data.forecast_typed_value = typed;
      data.forecast_value = forecast;
      data.forecast_is_numeric = !isNaN(forecast);
      data.cumulative_score_before_feedback = cumulativeScore;
    }
  };
}

function buildForecastFeedbackTrial(roundIndex, actualValue) {
  return {
    type: "survey-text",
    questions: [
      {
        prompt: function() {
          const forecast = latestForecast;
          const scoreInfo = applyForecastScoreOnce(
            roundIndex,
            forecast,
            actualValue
          );

          return renderForecastFeedback(
            actualValue,
            forecast,
            scoreInfo.points_earned
          );
        },
        name: "typed_actual_value",
        required: true
      }
    ],
    on_load: function() {
      restrictSurveyTextInputToDigits();
    },
    data: {
      phase: "forecast_feedback_recitation",
      round_index: roundIndex,
      true_value: actualValue
    },
    on_finish: function(data) {
      const typed = getSurveyTextAnswer(data, "typed_actual_value");
      const forecast = latestForecast;
      const scoreInfo = applyForecastScoreOnce(
        roundIndex,
        forecast,
        actualValue
      );

      const typedCorrectly = String(typed).trim() === String(actualValue);

      data.forecast_value = forecast;
      data.forecast_error = Math.abs(forecast - actualValue);
      data.points_earned = scoreInfo.points_earned;
      data.cumulative_score = cumulativeScore;
      data.typed_actual_value = typed;
      data.typed_actual_correct = typedCorrectly;
    }
  };
}

function buildForecastFeedbackLoop(roundIndex, actualValue) {
  return {
    timeline: [
      buildForecastFeedbackTrial(roundIndex, actualValue)
    ],
    loop_function: function(data) {
      const lastTrial = data.values()[0];

      // Repeat the same feedback screen until they type the actual value correctly.
      return !lastTrial.typed_actual_correct;
    }
  };
}


function buildScoreSummaryTrial() {
  return {
    type: "html-button-response",
    stimulus: function() {
      const bonusPayment = computeBonusPayment(cumulativeScore);
      const totalPayment = FLAT_FEE_DOLLARS + bonusPayment;

      return renderInformationalPage(`
        <h2>Results</h2>

        <p>
          Your final score is:
        </p>

        <div style="
          font-size: 48px;
          font-weight: bold;
          margin: 24px 0;
        ">
          ${cumulativeScore}
        </div>

        <div style="
          margin-top: 34px;
          font-size: 22px;
          line-height: 1.6;
        ">
          <p>
            Your participation payment is:
            <strong>${formatDollars(FLAT_FEE_DOLLARS)}</strong>
          </p>

          <p>
            Your bonus payment is:
            <strong>${formatDollars(bonusPayment)}</strong>
          </p>

          <p style="
            font-size: 26px;
            margin-top: 22px;
          ">
            Total payment:
            <strong>${formatDollars(totalPayment)}</strong>
          </p>
        </div>

        <p style="margin-top: 30px;">
          Click below to continue.
        </p>
      `);
    },
    choices: ["Continue"],
    data: {
      phase: "score_summary"
    },
    on_finish: function(data) {
      const bonusPayment = computeBonusPayment(cumulativeScore);
      const totalPayment = FLAT_FEE_DOLLARS + bonusPayment;

      data.final_score = cumulativeScore;
      data.flat_fee_dollars = FLAT_FEE_DOLLARS;
      data.bonus_payment_dollars = Number(bonusPayment.toFixed(2));
      data.total_payment_dollars = Number(totalPayment.toFixed(2));
      data.expected_score_for_payment = EXPECTED_SCORE_FOR_PAYMENT;
      data.expected_bonus_dollars = EXPECTED_BONUS_DOLLARS;
    }
  };
}

function buildFeedbackTrial() {
  return {
    type: "survey-text",
    questions: [
      {
        prompt: `
          ${surveyTextLayoutCss({
            minHeight: "88vh",
            inputWidth: "600px",
            inputHeight: "120px",
            inputFontSize: "18px",
            inputMarginTop: "20px",
            buttonMarginTop: "18px"
          })}

          ${renderInformationalPage(`
            <h2>Feedback</h2>

            <p>
              Before submitting, please let us know if you had any comments,
              technical problems, or anything confusing about the experiment.
            </p>

            <p>
              You may leave this blank if you have no comments.
            </p>
          `)}
        `,
        name: "participant_feedback",
        rows: 6,
        columns: 60,
        required: false
      }
    ],
    button_label: "Continue",
    data: {
      phase: "feedback"
    },
    on_finish: function(data) {
      const feedback = getSurveyTextAnswer(data, "participant_feedback");
      data.participant_feedback = feedback;
      participantFeedback = feedback;
    }
  };
}


function buildMainExperiment(assignment) {
  const timeline = [];

  const arValues = assignment.ar1.values;
  const distractionTasks = assignment.distraction.tasks;

  if (arValues.length < MAX_TRIALS) {
    throw new Error(
      "Assignment has only " + arValues.length + " AR(1) values but max_trials is " + MAX_TRIALS
    );
  }

  if (distractionTasks.length < MAX_TRIALS) {
    throw new Error(
      "Assignment has only " + distractionTasks.length +
      " distraction tasks but max_trials is " + MAX_TRIALS
    );
  }

  const nTrials = Math.min(MAX_TRIALS, arValues.length, distractionTasks.length);

  // Passive observation phase
  for (let i = 0; i < Math.min(FORECAST_START_INDEX, nTrials); i++) {
    timeline.push(buildDistractorBlock(i, distractionTasks[i]));
    timeline.push(buildValueRecallLoop(i, arValues[i]));
  }

  // Forecasting phase
  for (let i = FORECAST_START_INDEX; i < nTrials; i++) {
    const previousValue = arValues[i - 1];
    const actualValue = arValues[i];

    timeline.push(buildDistractorBlock(i, distractionTasks[i]));
    timeline.push(buildForecastTrial(i, previousValue));
    timeline.push(buildForecastFeedbackLoop(i, actualValue));
  }

  return timeline;
}


function buildPassedOnlyTimeline(
  instructions1Html,
  instructions2Html,
  instructions3Html,
  instructions4Html,
  finishedHtml,
  assignment
)
  {
  const passedTimeline = [];

  passedTimeline.push(...buildInstructions(instructions1Html, instructions2Html, instructions3Html, instructions4Html));
  passedTimeline.push(...buildMainExperiment(assignment));

  passedTimeline.push(buildScoreSummaryTrial());
  passedTimeline.push(buildFeedbackTrial());

  passedTimeline.push({
    type: "html-button-response",
    stimulus: renderInformationalPage(finishedHtml),
    choices: ["Submit"],
    data: {
      phase: "finished"
    }
  });

  passedTimeline.push(buildExitFullscreenTrial("experiment_complete"));

  return {
    timeline: passedTimeline,
    conditional_function: function() {
      return !failedCompetency;
    }
  };
}


function buildExperimentTimeline(assignment, html) {
  const timeline = [];  

  timeline.push(buildEnterFullscreenTrial());
  timeline.push(...buildCompetencyCheck(html));
  timeline.push(
    buildPassedOnlyTimeline(
      html.instructions1,
      html.instructions2,
      html.instructions3,
      html.instructions4,
      html.finished,
      assignment
    )
  );

  return timeline;
}

async function runExperiment() {
  try {
    const assignment = await loadAssignment();
    const html = await loadHtmlFiles({
      competency_failure: "/static/html/competency_failure.html",
      competency_intro: "/static/html/competency_intro.html",
      competency_q1: "/static/html/competency_q1.html",
      competency_q2: "/static/html/competency_q2.html",
      competency_q3: "/static/html/competency_q3.html",
      finished: "/static/html/finished.html",
      instructions1: "/static/html/instructions1.html",
      instructions2: "/static/html/instructions2.html",
      instructions3: "/static/html/instructions3.html",
      instructions4: "/static/html/instructions4.html"
    })

    console.log("Loaded assignment:", assignment);

    const timeline = buildExperimentTimeline(assignment, html);

    jsPsych.init({
      display_element: "jspsych-target",
      timeline: timeline,

      on_data_update: function(data) {
        data.uniqueId = uniqueId;
        data.prolific_pid = CONFIG.prolificPid;
        data.study_id = CONFIG.studyId;
        data.session_id = CONFIG.sessionId;
        data.attempt = CONFIG.attempt;
        data.condition = condition;
        data.counterbalance = counterbalance;
        data.assignment_slot = assignment.slot;
        data.rho = assignment.rho;
        data.start_type = assignment.start_type;
        data.codeversion = codeversion;
        data.failed_competency = failedCompetency;
        data.fullscreen_exit_count = fullscreenExitCount;
        data.is_fullscreen = document.fullscreenElement !== null;
        data.fullscreen_monitoring_active = fullscreenMonitoringActive;

        try {
          experiment.recordTrialData(data);
        } catch (error) {
          console.error("Could not queue this trial:", data, error);
        }
      },

      on_finish: function() {
        finishExperiment();
      }
    });
  } catch (error) {
    console.error(error);

    document.body.innerHTML = renderFatalError(
      "The experiment could not be loaded.",
      error.message,
      contact_address
    );
  }
}

/**
 * Submit the session and send the participant back to Prolific.
 *
 * Their submission is only registered once they reach the Prolific URL, so the
 * redirect matters as much as the data save. If it fails we surface the link
 * and the completion code rather than leaving them on a dead page.
 */
async function finishExperiment() {
  document.body.innerHTML = renderStatusPage(
    "Saving your responses...",
    "Please do not close this window."
  );

  try {
    const result = await experiment.complete({
      score: cumulativeScore,
      failedCompetency: failedCompetency,
      feedback: participantFeedback,
      fullscreenExitCount: fullscreenExitCount
    });

    document.body.innerHTML = renderStatusPage(
      "Returning you to Prolific...",
      `If you are not redirected within a few seconds,
       <a href="${result.completionUrl}">click here to complete your submission</a>.`
    );

    // Give the browser a moment to paint the message before navigating.
    setTimeout(function() {
      if (!experiment.returnToProlific(result)) {
        window.location.replace(result.fallbackUrl);
      }
    }, 1200);
  } catch (error) {
    console.error("Could not submit the session:", error);

    document.body.innerHTML = renderFatalError(
      "We could not reach our server to record your submission.",
      "Your responses up to this point have been saved. Please email " +
      contact_address + " with your Prolific ID so we can complete your payment " +
      "manually, and use the 'Return submission' option on Prolific only if we ask you to.",
      contact_address
    );
  }
}

runExperiment();
