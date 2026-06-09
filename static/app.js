(() => {
    const modal = document.querySelector("[data-order-modal]");
    const form = document.querySelector("[data-order-form]");
    const status = document.querySelector("[data-form-status]");
    const sourceInput = form?.elements.source;
    const phoneInput = form?.elements.phone;
    const submitButton = form?.querySelector("[type='submit']");
    const openButtons = document.querySelectorAll("[data-order-source]");
    const closeButtons = document.querySelectorAll("[data-modal-close]");

    if (!modal || !form || !status || !sourceInput || !phoneInput || !submitButton) {
        return;
    }

    const setStatus = (type, message) => {
        status.textContent = message;
        status.className = `form-status is-visible is-${type}`;
    };

    const clearStatus = () => {
        status.textContent = "";
        status.className = "form-status";
    };

    const isValidPhone = (phone) => {
        const value = phone.trim();
        const digits = value.replace(/\D/g, "");

        return digits.length >= 10 && digits.length <= 15 && !/[^\d\s()+.-]/.test(value);
    };

    const openModal = (source) => {
        sourceInput.value = source || "Форма заявки";
        clearStatus();
        modal.hidden = false;
        document.body.classList.add("modal-open");
        window.setTimeout(() => phoneInput.focus(), 0);
    };

    const closeModal = () => {
        modal.hidden = true;
        document.body.classList.remove("modal-open");
        clearStatus();
        form.reset();
        sourceInput.value = "Форма заявки";
    };

    openButtons.forEach((button) => {
        button.addEventListener("click", () => {
            openModal(button.dataset.orderSource);
        });
    });

    closeButtons.forEach((button) => {
        button.addEventListener("click", closeModal);
    });

    modal.addEventListener("click", (event) => {
        if (event.target === modal) {
            closeModal();
        }
    });

    document.addEventListener("keydown", (event) => {
        if (event.key === "Escape" && !modal.hidden) {
            closeModal();
        }
    });

    form.addEventListener("submit", async (event) => {
        event.preventDefault();
        clearStatus();

        const formData = new FormData(form);
        const payload = {
            phone: String(formData.get("phone") || "").trim(),
            email: String(formData.get("email") || "").trim(),
            comment: String(formData.get("comment") || "").trim(),
            source: String(formData.get("source") || "Форма заявки").trim(),
        };

        if (!payload.phone && !payload.email && !payload.comment) {
            setStatus("error", "Заполните телефон, чтобы отправить заявку.");
            phoneInput.focus();
            return;
        }

        if (!isValidPhone(payload.phone)) {
            setStatus("error", "Укажите корректный телефон: минимум 10 цифр, можно использовать +, пробелы, скобки и дефисы.");
            phoneInput.focus();
            return;
        }

        const privacyCheckbox = form.querySelector('[name="privacy_agree"]');
        if (privacyCheckbox && !privacyCheckbox.checked) {
            setStatus("error", "Необходимо дать согласие на обработку персональных данных.");
            privacyCheckbox.focus();
            return;
        }

        submitButton.disabled = true;

        try {
            const response = await fetch("/order", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                },
                body: JSON.stringify(payload),
            });
            const result = await response.json().catch(() => ({}));

            if (!response.ok) {
                throw new Error(result.error || "Не удалось отправить заявку. Попробуйте позже.");
            }

            form.reset();
            sourceInput.value = payload.source;
            setStatus("success", "Заявка отправлена. Мы получили данные и свяжемся с вами для уточнения деталей.");
        } catch (error) {
            setStatus("error", error.message || "Не удалось отправить заявку. Попробуйте позже.");
        } finally {
            submitButton.disabled = false;
        }
    });
})();
