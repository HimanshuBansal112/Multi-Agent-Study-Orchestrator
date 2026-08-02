document.addEventListener('DOMContentLoaded', () => {
    loadQuiz();
});

let quizData = null;
let userAnswers = {};

async function loadQuiz() {
    try {
        let response = await fetch('/DataBase/form.json');
        if (!response.ok) {
            console.log("/DataBase/form.json not available, trying local copy form.json");
            response = await fetch('form.json');
        }
        if (!response.ok) {
            console.warn("form.json not found, falling back to form - demo.json");
            response = await fetch('form - demo.json');
        }
        
        quizData = await response.json();
        renderQuiz(quizData);
    } catch (err) {
        console.error("Failed to load quiz data:", err);
        document.getElementById('questions-container').innerHTML = `
            <div class="question-card" style="text-align: center; color: var(--error);">
                <strong>✖ Error Loading Quiz</strong><br>
                Please ensure form.json or form - demo.json is present in the frontend directory.
            </div>
        `;
    }
}

function renderQuiz(quiz) {
    const container = document.getElementById('questions-container');
    container.innerHTML = '';
    
    document.getElementById('stat-mcq').textContent = `Single Choice (MCQ): ${quiz.mcq || 0}`;
    document.getElementById('stat-multi').textContent = `Multiple Choice: ${quiz.multi_choice || 0}`;
    document.getElementById('stat-blank').textContent = `Fill in Blank: ${quiz.fill_in_blank || 0}`;
    
    let totalPoints = 0;
    const items = quiz.data || [];
    let qCount = 0;
    
    items.forEach((req, idx) => {
        if (!req.createItem) return;
        
        qCount++;
        const item = req.createItem.item;
        const qItem = item.questionItem;
        const question = qItem.question;
        const grading = question.grading || {};
        const points = grading.pointValue || 0;
        totalPoints += points;
        
        userAnswers[idx] = [];
        
        const card = document.createElement('div');
        card.className = 'question-card';
        card.id = `question-${idx}`;
        
        const header = document.createElement('div');
        header.className = 'card-header';
        
        const titleCol = document.createElement('div');
        titleCol.style.display = 'flex';
        titleCol.style.flexDirection = 'column';
        titleCol.style.gap = '8px';
        
        const meta = document.createElement('div');
        meta.className = 'question-meta';
        meta.innerHTML = `
            <span class="q-num">Question ${qCount}</span>
            <span class="q-points">${points} Point${points !== 1 ? 's' : ''} ${question.required ? '<span style="color: var(--error)">*</span>' : ''}</span>
        `;
        
        const title = document.createElement('h3');
        title.className = 'question-title';
        title.textContent = item.title;
        
        titleCol.appendChild(meta);
        titleCol.appendChild(title);
        header.appendChild(titleCol);
        card.appendChild(header);
        
        if (item.description) {
            const desc = document.createElement('p');
            desc.className = 'question-desc';
            desc.textContent = item.description;
            card.appendChild(desc);
        }
        
        if (question.choiceQuestion) {
            const choiceQ = question.choiceQuestion || {};
            const type = choiceQ.type || 'RADIO';
            const options = choiceQ.options || [];
            
            const optionsList = document.createElement('div');
            optionsList.className = 'options-list';
            
            options.forEach((opt, oIdx) => {
                const letter = String.fromCharCode(65 + oIdx);
                const optionItem = document.createElement('div');
                optionItem.className = 'option-item';
                optionItem.dataset.value = opt.value;
                optionItem.dataset.qIdx = idx;
                optionItem.dataset.type = type;
                
                const prefixClass = type === 'CHECKBOX' ? 'square' : 'circle';
                optionItem.innerHTML = `
                    <div class="option-prefix ${prefixClass}">${letter}</div>
                    <div class="option-text">${escapeHtml(opt.value)}</div>
                `;
                
                optionItem.addEventListener('click', () => handleOptionSelect(optionItem));
                optionsList.appendChild(optionItem);
            });
            
            card.appendChild(optionsList);
        } else if (question.textQuestion) {
            const inputContainer = document.createElement('div');
            inputContainer.className = 'text-input-container';
            
            const textInput = document.createElement('input');
            textInput.type = 'text';
            textInput.className = 'quiz-text-input';
            textInput.placeholder = 'Type your answer here...';
            textInput.dataset.qIdx = idx;
            textInput.addEventListener('input', (e) => handleTextInput(e.target));
            
            inputContainer.appendChild(textInput);
            card.appendChild(inputContainer);
        }
        
        const feedbackBox = document.createElement('div');
        feedbackBox.className = 'feedback-box';
        feedbackBox.id = `feedback-${idx}`;
        card.appendChild(feedbackBox);
        
        container.appendChild(card);
    });
    
    window.totalPoints = totalPoints;
    checkFormValidity();
}

function handleOptionSelect(optionEl) {
    const qIdx = parseInt(optionEl.dataset.qIdx);
    const type = optionEl.dataset.type;
    const value = optionEl.dataset.value;
    
    if (window.quizSubmitted) return;
    
    const card = document.getElementById(`question-${qIdx}`);
    const siblings = card.querySelectorAll('.option-item');
    
    if (type === 'RADIO') {
        siblings.forEach(el => el.classList.remove('selected'));
        optionEl.classList.add('selected');
        userAnswers[qIdx] = [value];
    } else {
        optionEl.classList.toggle('selected');
        if (optionEl.classList.contains('selected')) {
            if (!userAnswers[qIdx].includes(value)) {
                userAnswers[qIdx].push(value);
            }
        } else {
            userAnswers[qIdx] = userAnswers[qIdx].filter(v => v !== value);
        }
    }
    
    checkFormValidity();
}

function handleTextInput(inputEl) {
    const qIdx = parseInt(inputEl.dataset.qIdx);
    const value = inputEl.value.trim();
    
    if (window.quizSubmitted) return;
    
    if (value.length > 0) {
        userAnswers[qIdx] = [value];
    } else {
        userAnswers[qIdx] = [];
    }
    
    checkFormValidity();
}

function checkFormValidity() {
    const submitBtn = document.getElementById('submit-btn');
    if (!quizData) return;
    
    let isValid = true;
    
    quizData.data.forEach((req, idx) => {
        if (!req.createItem) return;
        
        const question = req.createItem.item.questionItem.question;
        if (question.required) {
            if (!userAnswers[idx] || userAnswers[idx].length === 0) {
                isValid = false;
            }
        }
    });
    
    submitBtn.disabled = !isValid;
}

function submitQuiz() {
    if (window.quizSubmitted) return;
    window.quizSubmitted = true;
    
    let earnedPoints = 0;
    
    quizData.data.forEach((req, idx) => {
        if (!req.createItem) return;
        
        const qItem = req.createItem.item.questionItem;
        const question = qItem.question;
        const grading = question.grading || {};
        const points = grading.pointValue || 0;
        
        const correctAnswers = (grading.correctAnswers && grading.correctAnswers.answers) 
            ? grading.correctAnswers.answers.map(a => a.value) 
            : [];
            
        const selected = userAnswers[idx] || [];
        let isCorrect = false;
        
        const card = document.getElementById(`question-${idx}`);
        const feedbackBox = document.getElementById(`feedback-${idx}`);
        
        if (question.choiceQuestion) {
            isCorrect = correctAnswers.length > 0 &&
                selected.length === correctAnswers.length &&
                selected.every(v => correctAnswers.includes(v));
                
            const optionEls = card.querySelectorAll('.option-item');
            optionEls.forEach(el => {
                const val = el.dataset.value;
                const isSelected = el.classList.contains('selected');
                const isRight = correctAnswers.includes(val);
                
                if (isRight) {
                    el.classList.add('correct-answer');
                } else if (isSelected && !isRight) {
                    el.classList.add('wrong-answer');
                }
                
                el.style.transform = 'none';
                el.style.cursor = 'default';
            });
        } else if (question.textQuestion) {
            const typedVal = selected[0] || '';
            isCorrect = correctAnswers.some(ans => typedVal.toLowerCase().trim() === ans.toLowerCase().trim());
            
            const textInput = card.querySelector('.quiz-text-input');
            if (textInput) {
                textInput.disabled = true;
                if (isCorrect) {
                    textInput.classList.add('correct-answer');
                } else {
                    textInput.classList.add('wrong-answer');
                }
            }
        }
        
        const feedbackText = isCorrect
            ? (grading.whenRight ? grading.whenRight.text : (grading.generalFeedback ? grading.generalFeedback.text : 'Great job!'))
            : (grading.whenWrong ? grading.whenWrong.text : (grading.generalFeedback ? grading.generalFeedback.text : 'Please review the notes and try again.'));
            
        if (isCorrect) {
            earnedPoints += points;
            feedbackBox.className = 'feedback-box correct';
            feedbackBox.innerHTML = `
                <div class="feedback-title">
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 15l-5-5 1.41-1.41L10 14.17l7.59-7.59L19 8l-9 9z"/></svg>
                    Correct (+${points} Point${points !== 1 ? 's' : ''})
                </div>
                <div>${feedbackText}</div>
            `;
        } else {
            feedbackBox.className = 'feedback-box wrong';
            feedbackBox.innerHTML = `
                <div class="feedback-title">
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><path d="M12 2C6.47 2 2 6.47 2 12s4.47 10 10 10 10-4.47 10-10S17.53 2 12 2zm5 13.59L15.59 17 12 13.41 8.41 17 7 15.59 10.59 12 7 8.41 8.41 7 12 10.59 15.59 7 17 8.41 13.41 12 17 15.59z"/></svg>
                    Incorrect (0 Points)
                </div>
                <div style="margin-bottom: 8px;"><strong>Correct Answer:</strong> ${escapeHtml(correctAnswers.join(' OR '))}</div>
                <div>${feedbackText}</div>
            `;
        }
        feedbackBox.style.display = 'block';
    });
    
    const scoreContainer = document.getElementById('score-container');
    document.getElementById('score-val').textContent = `${earnedPoints} / ${window.totalPoints}`;
    scoreContainer.style.display = 'flex';
    
    document.getElementById('submit-btn').style.display = 'none';
    document.getElementById('reset-btn').style.display = 'flex';
    
    window.scrollTo({ top: 0, behavior: 'smooth' });
}

function resetQuiz() {
    window.quizSubmitted = false;
    renderQuiz(quizData);
    
    document.getElementById('submit-btn').style.display = 'flex';
    document.getElementById('reset-btn').style.display = 'none';
    document.getElementById('score-container').style.display = 'none';
}

function escapeHtml(str) {
    if (!str) return '';
    return str
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}
