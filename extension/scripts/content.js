// content.js - JobAutoFill Intelligent Scraper and Autofiller
// Supports Spanish, English, French, German, Portuguese, Italian

(function () {
  // Prevent duplicate injections
  if (window.__jobAutoFillInjected) {
    return;
  }
  window.__jobAutoFillInjected = true;

  // Fallback demo profile for standalone testing without extension runtime
  const STANDALONE_DEMO_PROFILE = {
    first_name: 'Christian',
    last_name: 'Rivero',
    full_name: 'Christian Rivero',
    email: 'christian.rivero@ejemplo.com',
    phone_prefix: '+34',
    phone: '612345678',
    id_document: '12345678Z',
    address: 'Paseo de la Castellana 100',
    city: 'Madrid',
    postal_code: '28046',
    state: 'Madrid',
    country: 'España',
    current_role: 'Senior Software Engineer',
    current_company: 'Tech Solutions S.L.',
    years_experience: '6',
    salary_expectation: '58000',
    notice_period: '15 días',
    work_modality: 'Remoto',
    linkedin: 'https://www.linkedin.com/in/christian-rivero',
    github: 'https://github.com/christian-rivero',
    website: 'https://christianrivero.dev',
    twitter: 'https://x.com/crivero_dev',
    cv_path: '/Users/christian.rivero/Documents/CV_Christian_Rivero.pdf',
    work_authorization: 'yes',
    visa_sponsorship: 'no',
    english_level: 'Professional / Fluent (C1/C2)',
    disability: 'no',
    cover_letter: 'Estimado equipo de selección,\n\nCuento con amplia experiencia en desarrollo de software, arquitectura de sistemas e integración continua. Me motiva enormemente la oportunidad de aportar soluciones técnicas escalables y de alto impacto a su equipo.\n\nAtentamente,\nChristian Rivero'
  };

  // Helper: Normalize string by stripping accents/diacritics and converting to lowercase
  function normalizeText(str) {
    if (!str || typeof str !== 'string') return '';
    return str
      .replace(/ß/g, 'ss')
      .normalize('NFD')
      .replace(/[\u0300-\u036f]/g, '') // remove diacritics (á -> a, é -> e, ñ -> n)
      .toLowerCase()
      .trim();
  }

  // EXHAUSTIVE MULTI-LANGUAGE HEURISTIC RULES
  // Languages: Spanish (ES), English (EN), French (FR), German (DE), Portuguese (PT), Italian (IT)
  const FIELD_RULES = [
    {
      key: 'first_name',
      // ES: nombre, primer nombre | EN: first name, given name, forename | FR: prenom | DE: vorname | IT: nome | PT: primeiro nome
      regex: /(?:^|[_\-\s])(first[_\-\s]?name|primer[_\-\s]?nombre|given[_\-\s]?name|forename|prenom|vorname|primeiro[_\-\s]?nome|fname|\bnombre\b|\bnome\b)(?:$|[_\-\s])/i,
      negative: /(?:last|full|apellido|company|user|empresa|sur[_\-\s]?name|cognome|nachname|sobrenome|usuario|completo|complet|vollstandig)/i,
      priority: 10
    },
    {
      key: 'last_name',
      // ES: apellido(s) | EN: last name, surname, family name | FR: nom de famille | DE: nachname, familienname | IT: cognome | PT: sobrenome, apelido
      regex: /(?:^|[_\-\s])(last[_\-\s]?name|apellidos?|sur[_\-\s]?name|family[_\-\s]?name|primer[_\-\s]?apellido|segundo[_\-\s]?apellido|nom[_\-\s]?de[_\-\s]?famille|nachname|familienname|cognome|sobrenome|apelido|lname)(?:$|[_\-\s])/i,
      negative: /(?:first|primer\s*nombre|full|nombre\s*completo|prenom|vorname)/i,
      priority: 10
    },
    {
      key: 'full_name',
      // ES: nombre completo | EN: full name, candidate name | FR: nom complet | DE: vollstandiger name | IT: nome e cognome | PT: nome completo
      regex: /(?:^|[_\-\s])(full[_\-\s]?name|nombre[_\-\s]?(?:y[_\-\s]?apellidos|completo)|candidate[_\-\s]?name|applicant[_\-\s]?name|your[_\-\s]?name|tu[_\-\s]?nombre|nom[_\-\s]?complet|vollstandiger[_\-\s]?name|nome[_\-\s]?e[_\-\s]?cognome|nome[_\-\s]?completo)(?:$|[_\-\s])/i,
      negative: /(?:first[_\-\s]?name|last[_\-\s]?name|primer[_\-\s]?nombre|apellido|prenom|vorname)/i,
      priority: 11
    },
    {
      key: 'email',
      types: ['email'],
      // ES: correo | EN: email | FR: courriel, e-mail | DE: e-mail, mailadresse | IT/PT: email
      regex: /(?:^|[_\-\s])(e[_\-\s]?mail|correo(?:[_\-\s]?electronico)?|courriel|mailadresse|email[_\-\s]?address)(?:$|[_\-\s])/i,
      priority: 10
    },
    {
      key: 'phone_prefix',
      // Dialing / Country codes: prefijo, phone prefix, calling code, dial code, indicatif
      regex: /(?:^|[_\-\s])(phone[_\-\s]?prefix|prefijo|country[_\-\s]?code|calling[_\-\s]?code|dial[_\-\s]?code|indicatif|vorwahl)(?:$|[_\-\s])/i,
      priority: 12
    },
    {
      key: 'phone',
      types: ['tel'],
      // ES: telefono, movil, celular | EN: phone, mobile, cell | FR: telephone, portable | DE: telefon, handy | IT: telefono, cellulare | PT: telefone, telemovel
      regex: /(?:^|[_\-\s])(phone(?:[_\-\s]?number)?|telefon(?:nummer|[_\-\s]?number)?|telefono|movil|celular|contact[_\-\s]?number|cell[_\-\s]?phone|portable|handy(?:nummer)?|telemovel|rufnummer)(?:$|[_\-\s])/i,
      negative: /(?:prefix|prefijo|country[_\-\s]?code|indicatif|vorwahl)/i,
      priority: 10
    },
    {
      key: 'id_document',
      // DNI, NIE, NIF, CIF, Passport, Pasaporte, Tax ID, SSN, Cedula, Carte d'identite
      regex: /(?:^|[_\-\s])(dni|nie|nif|cif|pasaporte|passport|id[_\-\s]?number|cedula|identificacion|tax[_\-\s]?id|ssn|carte[_\-\s]?identite|ausweis)(?:$|[_\-\s])/i,
      priority: 8
    },
    {
      key: 'address',
      // ES: direccion, calle, domicilio | EN: address, street | FR: adresse, rue | DE: adresse, strasse, anschrift | IT: indirizzo, via | PT: endereco, rua
      regex: /(?:^|[_\-\s])(address(?:[_\-\s]?line[_\-\s]?[1]?)?|direccion|calle|domicilio|residence|street|adresse|strasse|anschrift|indirizzo|endereco|logradouro)(?:$|[_\-\s])/i,
      negative: /(?:email|correo|ip|mac|web|url|mail)/i,
      priority: 9
    },
    {
      key: 'city',
      // ES: ciudad, localidad, municipio, poblacion | EN: city, town | FR: ville, commune | DE: stadt, ort | IT: citta, comune | PT: cidade, municipio
      regex: /(?:^|[_\-\s])(city|ciudad|localidad|municipio|poblacion|town|ville|commune|stadt|wohnort|citta|cidade)(?:$|[_\-\s])/i,
      priority: 9
    },
    {
      key: 'postal_code',
      // ES: codigo postal, cp | EN: postal code, zip code, postcode | FR: code postal | DE: postleitzahl, plz | IT: cap | PT: cep, codigo postal
      regex: /(?:^|[_\-\s])(postal[_\-\s]?code|codigo[_\-\s]?postal|zip(?:[_\-\s]?code)?|postcode|code[_\-\s]?postal|postleitzahl|plz|cap\b|cep\b|c\.?p\.?)(?:$|[_\-\s])/i,
      priority: 9
    },
    {
      key: 'state',
      // ES: provincia, region, comunidad autonoma | EN: state, province, county | FR: departement, region | DE: bundesland, kanton | IT: provincia, regione | PT: estado, distrito
      regex: /(?:^|[_\-\s])(state|provincia|region|comunidad(?:[_\-\s]?autonoma)?|department|departement|county|bundesland|kanton|distrito|regione)(?:$|[_\-\s])/i,
      priority: 8
    },
    {
      key: 'country',
      // ES: pais, nacionalidad | EN: country, nationality | FR: pays, nationalite | DE: land, staat | IT: paese, stato | PT: pais, nacionalidade
      regex: /(?:^|[_\-\s])(country|pais|nacion|nationality|nacionalidad|pays|nationalite|land|staat|paese|cidadania)(?:$|[_\-\s])/i,
      negative: /(?:authorized|work|autorizacion|permiso|autorizado|derecho|eligib|travail|arbeitserlaubnis|calling|dial|prefix|prefijo)/i,
      priority: 8
    },
    {
      key: 'linkedin',
      regex: /(?:^|[_\-\s])(linkedin|linked[_\-\s]?in)(?:$|[_\-\s])/i,
      priority: 13
    },
    {
      key: 'github',
      regex: /(?:^|[_\-\s])(github|git[_\-\s]?hub)(?:$|[_\-\s])/i,
      priority: 13
    },
    {
      key: 'website',
      // Portfolio, website, web personal, sitio web, siteweb, eigene webseite
      regex: /(?:^|[_\-\s])(portfolio|portafolio|website|web[_\-\s]?personal|sitio[_\-\s]?web|personal[_\-\s]?site|other[_\-\s]?website|webseite|site[_\-\s]?internet)(?:$|[_\-\s])/i,
      negative: /(?:linkedin|github|twitter|facebook|instagram)/i,
      priority: 9
    },
    {
      key: 'twitter',
      regex: /(?:^|[_\-\s])(twitter|x\.com|twitter[_\-\s]?handle)(?:$|[_\-\s])/i,
      priority: 10
    },
    {
      key: 'current_role',
      // ES: puesto actual, cargo actual, titular | EN: current role, job title, headline | FR: poste actuel, profession | DE: aktuelle position, beruf | IT: posizione attuale | PT: cargo atual
      regex: /(?:^|[_\-\s])(current[_\-\s]?(?:title|role|position|job)|puesto[_\-\s]?(?:actual)?|titular|cargo[_\-\s]?(?:actual)?|job[_\-\s]?title|headline|profesion|poste[_\-\s]?actuel|aktuelle[_\-\s]?position|berufsbezeichnung|posizione[_\-\s]?attuale|cargo[_\-\s]?atual)(?:$|[_\-\s])/i,
      priority: 8
    },
    {
      key: 'current_company',
      // ES: empresa actual, empleador | EN: current company, employer | FR: entreprise actuelle, employeur | DE: arbeitgeber, firma | IT: azienda attuale | PT: empresa atual
      regex: /(?:^|[_\-\s])(current[_\-\s]?company|empresa[_\-\s]?(?:actual)?|compania[_\-\s]?(?:actual)?|employer|actual[_\-\s]?empleador|entreprise[_\-\s]?(?:actuelle)?|employeur|arbeitgeber|unternehmensname|azienda[_\-\s]?(?:attuale)?)(?:$|[_\-\s])/i,
      priority: 8
    },
    {
      key: 'years_experience',
      // ES: anos de experiencia | EN: years of experience | FR: annees d experience | DE: berufserfahrung, jahre erfahrung | IT: anni di experiencia | PT: anos de experiencia
      regex: /(?:^|[_\-\s])(years?[_\-\s]?(?:of)?[_\-\s]?exp(?:erience)?|anos?[_\-\s]?(?:de)?[_\-\s]?exp(?:eriencia)?|experiencia[_\-\s]?total|annees?[_\-\s]?(?:d['\s]?)?exp(?:erience)?|berufserfahrung|jahre[_\-\s]?erfahrung|anni[_\-\s]?(?:di)?[_\-\s]?esperienza)(?:$|[_\-\s])/i,
      priority: 9
    },
    {
      key: 'salary_expectation',
      // ES: salario deseado, sueldo, retribucion | EN: salary expectation, desired compensation | FR: pretentions salariales, salaire | DE: gehaltsvorstellung, wunschgehalt | IT: aspettativa retributiva | PT: pretensao salarial
      regex: /(?:^|[_\-\s])(salary(?:[_\-\s]?(?:expectation|desired))?|salario(?:[_\-\s]?(?:deseado|esperado))?|remuneracion|compensation|sueldo|retribucion|pretentions?[_\-\s]?salariales?|salaire|gehaltsvorstellung|wunschgehalt|aspettativa[_\-\s]?retributiva|pretensao[_\-\s]?salarial)(?:$|[_\-\s])/i,
      priority: 8
    },
    {
      key: 'notice_period',
      // ES: preaviso, disponibilidad, incorporacion | EN: notice period, availability, start date | FR: preavis, disponibilite | DE: kundigungsfrist, verfugbarkeit | IT: preavviso | PT: aviso previo
      regex: /(?:^|[_\-\s])(notice[_\-\s]?period|preaviso|incorporacion|disponibilidad|start[_\-\s]?date|earliest[_\-\s]?start|preavis|disponibilite|kundigungsfrist|verfugbarkeit|eintrittstermin|tempo[_\-\s]?di[_\-\s]?preavviso|aviso[_\-\s]?previo)(?:$|[_\-\s])/i,
      priority: 8
    },
    {
      key: 'work_authorization',
      // ES: permiso de trabajo, autorizacion legal | EN: authorized to work, work permit | FR: autorisation de travail | DE: arbeitserlaubnis | IT: permesso di soggiorno | PT: autorizacao de trabalho
      regex: /(?:^|[_\-\s])(authorized[_\-\s]?to[_\-\s]?work|work[_\-\s]?(?:authorization|permit|eligibility)|permiso[_\-\s]?(?:de)?[_\-\s]?trabajo|autorizacion[_\-\s]?legal|derecho[_\-\s]?(?:a|para)?[_\-\s]?trabajar|legally[_\-\s]?authorized|autorisation[_\-\s]?de[_\-\s]?travail|arbeitserlaubnis|arbeitsberechtigung|permesso[_\-\s]?di[_\-\s]?lavoro|autorizacao[_\-\s]?de[_\-\s]?trabalho)(?:$|[_\-\s])/i,
      priority: 9
    },
    {
      key: 'visa_sponsorship',
      // ES: patrocinio de visa/visado, requiere visa | EN: visa sponsorship, require visa | FR: parrainage de visa | DE: visumunterstutzung | IT: sponsorizzazione visto | PT: patrocinio de visto
      regex: /(?:^|[_\-\s])(sponsorship|visa[_\-\s]?sponsorship|patrocinio(?:[_\-\s]?de[_\-\s]?(?:visa|visado))?|require[_\-\s]?(?:visa|sponsorship)|necesita[_\-\s]?visado|besoin[_\-\s]?de[_\-\s]?visa|parrainage[_\-\s]?de[_\-\s]?visa|visumunterstutzung|sponsorizzazione[_\-\s]?del[_\-\s]?visto)(?:$|[_\-\s])/i,
      priority: 9
    },
    {
      key: 'cover_letter',
      // ES: carta de presentacion/motivacion | EN: cover letter, additional information | FR: lettre de motivation | DE: anschreiben | IT: lettera di presentazione | PT: carta de apresentacao
      regex: /(?:^|[_\-\s])(cover[_\-\s]?letter|carta[_\-\s]?(?:de)?[_\-\s]?(?:presentacion|motivacion)|comentarios?[_\-\s]?adicional(?:es)?|additional[_\-\s]?(?:info|notes|information)|resumen|summary|lettre[_\-\s]?de[_\-\s]?motivation|anschreiben|motivationsschreiben|lettera[_\-\s]?motivazionale|carta[_\-\s]?de[_\-\s]?apresentacao)(?:$|[_\-\s])/i,
      priority: 8
    },
    {
      key: 'cv_upload',
      types: ['file'],
      // ES: cv, curriculum, hoja de vida | EN: resume, cv, curriculum vitae | FR: cv | DE: lebenslauf | IT: curriculum | PT: curriculo
      regex: /(?:^|[_\-\s])(cv|resume|curriculum(?:[_\-\s]?vitae)?|curriculo|hoja[_\-\s]?de[_\-\s]?vida|upload[_\-\s]?cv|adjuntar[_\-\s]?cv|lebenslauf|attach[_\-\s]?resume)(?:$|[_\-\s])/i,
      priority: 15
    }
  ];

  // Helper: Extract and normalize text context around an element
  function getElementContext(el) {
    const texts = [];

    // Direct attributes
    if (el.id) texts.push(el.id);
    if (el.name) texts.push(el.name);
    if (el.placeholder) texts.push(el.placeholder);
    if (el.autocomplete) texts.push(el.autocomplete);
    if (el.title) texts.push(el.title);

    const ariaLabel = el.getAttribute('aria-label');
    if (ariaLabel) texts.push(ariaLabel);

    const dataAutomation = el.getAttribute('data-automation-id') || el.getAttribute('data-testid');
    if (dataAutomation) texts.push(dataAutomation);

    // Label by for attribute
    if (el.id) {
      try {
        const label = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
        if (label && label.innerText) texts.push(label.innerText);
      } catch (e) {
        // ignore selector errors
      }
    }

    // Parent label or enclosing container
    const parentLabel = el.closest('label');
    if (parentLabel && parentLabel.innerText) {
      texts.push(parentLabel.innerText);
    }

    // Fieldset legend if in radio/checkbox group
    const fieldset = el.closest('fieldset');
    if (fieldset) {
      const legend = fieldset.querySelector('legend');
      if (legend && legend.innerText) {
        texts.push(legend.innerText);
      }
    }

    // Preceding label or sibling in form group
    const container = el.closest('.form-group, .field, .form-field, .input-group, div, tr, li');
    if (container) {
      const containerLabel = container.querySelector('label, .label, dt, th, span.title, p.label, p.title');
      if (containerLabel && containerLabel.innerText && containerLabel !== parentLabel) {
        texts.push(containerLabel.innerText);
      }
    }

    // Previous element sibling
    const prev = el.previousElementSibling;
    if (prev && (prev.tagName === 'LABEL' || prev.tagName === 'SPAN' || prev.tagName === 'P') && prev.innerText) {
      texts.push(prev.innerText);
    }

    // Normalize all collected text (lowercased, accents removed)
    return normalizeText(texts.join(' '));
  }

  // Helper: Match element to a field key
  function identifyField(el) {
    const type = (el.type || 'text').toLowerCase();
    if (['submit', 'button', 'hidden', 'image', 'reset'].includes(type)) {
      return null;
    }

    const context = getElementContext(el);

    // If file input, high priority for CV upload
    if (type === 'file') {
      const cvRule = FIELD_RULES.find(r => r.key === 'cv_upload');
      if (cvRule.regex.test(context) || context.length < 5) {
        // Almost every file input in a job form is the CV/resume
        return 'cv_upload';
      }
    }

    let bestMatch = null;
    let highestScore = -1;

    for (const rule of FIELD_RULES) {
      let score = 0;

      // Check input types if restricted
      if (rule.types && rule.types.includes(type)) {
        score += 8;
      }

      // Negative match check
      if (rule.negative && rule.negative.test(context)) {
        continue;
      }

      // Primary regex match
      if (rule.regex.test(context)) {
        score += rule.priority;
        // Exact name or id bonus
        if (el.name && rule.regex.test(normalizeText(el.name))) score += 5;
        if (el.id && rule.regex.test(normalizeText(el.id))) score += 5;
        if (el.autocomplete && rule.regex.test(normalizeText(el.autocomplete))) score += 6;

        if (score > highestScore) {
          highestScore = score;
          bestMatch = rule.key;
        }
      }
    }

    return bestMatch;
  }

  // Apply value compatible with modern reactive frameworks (React, Vue, Angular, Workday)
  function setNativeValue(el, value) {
    if (el.value === value) return;

    // Focus element to trigger focus handlers
    el.dispatchEvent(new Event('focus', { bubbles: true }));

    const prototype = el instanceof HTMLTextAreaElement ? window.HTMLTextAreaElement.prototype : window.HTMLInputElement.prototype;
    const descriptor = Object.getOwnPropertyDescriptor(prototype, 'value');

    if (descriptor && descriptor.set) {
      descriptor.set.call(el, value);
    } else {
      el.value = value;
    }

    // Trigger standard input/change/blur events
    el.dispatchEvent(new Event('input', { bubbles: true, composed: true }));
    el.dispatchEvent(new Event('change', { bubbles: true, composed: true }));
    el.dispatchEvent(new Event('blur', { bubbles: true, composed: true }));
  }

  // Handle radio buttons (e.g., Work Authorization: Yes/No, Sponsorship: Yes/No)
  function setRadioValue(radioEl, desiredValue) {
    const valNorm = normalizeText(String(desiredValue));
    // Get text context of this specific radio button
    const radioContext = normalizeText(
      (radioEl.value || '') + ' ' +
      (radioEl.id ? document.querySelector(`label[for="${CSS.escape(radioEl.id)}"]`)?.innerText || '' : '') + ' ' +
      (radioEl.closest('label')?.innerText || '') + ' ' +
      (radioEl.nextElementSibling?.innerText || '')
    );

    const isYesDesired = ['yes', 'si', 'true', '1', 'oui', 'ja', 'sim'].includes(valNorm);
    const isNoDesired = ['no', 'false', '0', 'non', 'nein', 'nao'].includes(valNorm);

    let shouldCheck = false;

    if (isYesDesired) {
      if (/(?:^|[_\-\s])(yes|si|true|1|oui|ja|sim|autorizado|eligible)(?:$|[_\-\s])/i.test(radioContext)) {
        shouldCheck = true;
      }
    } else if (isNoDesired) {
      if (/(?:^|[_\-\s])(no|false|0|non|nein|nao|ineligible)(?:$|[_\-\s])/i.test(radioContext)) {
        shouldCheck = true;
      }
    } else if (radioContext.includes(valNorm) || normalizeText(radioEl.value) === valNorm) {
      shouldCheck = true;
    }

    if (shouldCheck && !radioEl.checked) {
      radioEl.checked = true;
      radioEl.dispatchEvent(new Event('click', { bubbles: true }));
      radioEl.dispatchEvent(new Event('input', { bubbles: true }));
      radioEl.dispatchEvent(new Event('change', { bubbles: true }));
      return true;
    }
    return false;
  }

  // Handle select inputs with multilingual synonyms
  function setSelectValue(selectEl, desiredValue) {
    const valNorm = normalizeText(String(desiredValue));
    let matchedOption = null;

    // Country synonyms mapping
    const COUNTRY_SYNONYMS = {
      'espana': ['espana', 'spain', 'espagne', 'spanien', 'es', 'esp'],
      'estados unidos': ['estados unidos', 'united states', 'usa', 'us', 'etats-unis', 'vereinigte staaten'],
      'mexico': ['mexico', 'mex', 'mx'],
      'colombia': ['colombia', 'col', 'co'],
      'argentina': ['argentina', 'arg', 'ar'],
      'chile': ['chile', 'chl', 'cl'],
      'reino unido': ['reino unido', 'united kingdom', 'uk', 'gb', 'royaume-uni', 'grossbritannien'],
      'francia': ['francia', 'france', 'frankreich', 'fr'],
      'alemania': ['alemania', 'germany', 'deutschland', 'allemagne', 'de'],
      'italia': ['italia', 'italy', 'italie', 'italien', 'it'],
      'portugal': ['portugal', 'pt']
    };

    const synonyms = COUNTRY_SYNONYMS[valNorm] || [valNorm];

    for (const opt of selectEl.options) {
      const optVal = normalizeText(opt.value);
      const optText = normalizeText(opt.text);

      if (valNorm === 'yes' || valNorm === 'si') {
        if (['yes', 'si', 'true', '1', 'y', 'oui', 'ja', 'sim'].includes(optVal) ||
            /(?:^|[_\-\s])(si|yes|true|oui|ja|sim|autorizado|eligible)(?:$|[_\-\s])/i.test(optText)) {
          matchedOption = opt;
          break;
        }
      } else if (valNorm === 'no') {
        if (['no', 'false', '0', 'n', 'non', 'nein', 'nao'].includes(optVal) ||
            /(?:^|[_\-\s])(no|false|non|nein|nao|ineligible)(?:$|[_\-\s])/i.test(optText)) {
          matchedOption = opt;
          break;
        }
      } else {
        // Check if option matches any of the synonyms
        for (const syn of synonyms) {
          if (optVal === syn || optText === syn || optText.includes(syn) || optVal.includes(syn)) {
            matchedOption = opt;
            break;
          }
        }
        if (matchedOption) break;
      }
    }

    if (matchedOption) {
      selectEl.value = matchedOption.value;
      selectEl.dispatchEvent(new Event('input', { bubbles: true }));
      selectEl.dispatchEvent(new Event('change', { bubbles: true }));
      return true;
    }
    return false;
  }

  // Convert base64 dataUrl to File and assign to file input via DataTransfer
  function injectCVFile(inputEl, cvFile) {
    try {
      if (!cvFile || !cvFile.dataUrl) return false;

      const arr = cvFile.dataUrl.split(',');
      const mime = arr[0].match(/:(.*?);/)?.[1] || 'application/pdf';
      const bstr = atob(arr[1]);
      let n = bstr.length;
      const u8arr = new Uint8Array(n);
      while (n--) {
        u8arr[n] = bstr.charCodeAt(n);
      }

      const file = new File([u8arr], cvFile.name || 'CV.pdf', {
        type: mime,
        lastModified: cvFile.lastModified || Date.now()
      });

      const dataTransfer = new DataTransfer();
      dataTransfer.items.add(file);
      inputEl.files = dataTransfer.files;

      inputEl.dispatchEvent(new Event('input', { bubbles: true }));
      inputEl.dispatchEvent(new Event('change', { bubbles: true }));
      return true;
    } catch (err) {
      console.warn('JobAutoFill: Error injecting CV via DataTransfer:', err);
      return false;
    }
  }

  // Main Autofill Routine
  function autofillJobForm(profile) {
    // If no profile provided or in standalone test mode, use fallback
    const targetProfile = profile || STANDALONE_DEMO_PROFILE;

    const elements = document.querySelectorAll('input, select, textarea');
    let filledCount = 0;
    const filledFields = [];

    // Compute full name if missing
    const fullName = targetProfile.full_name || `${targetProfile.first_name || ''} ${targetProfile.last_name || ''}`.trim();

    elements.forEach(el => {
      const fieldKey = identifyField(el);
      if (!fieldKey) return;

      let valueToFill = targetProfile[fieldKey];

      // Fallbacks for names
      if (fieldKey === 'full_name' && !valueToFill) {
        valueToFill = fullName;
      } else if (fieldKey === 'first_name' && !valueToFill && fullName) {
        valueToFill = fullName.split(' ')[0];
      }

      const type = (el.type || '').toLowerCase();

      // Apply value based on element type
      if (fieldKey === 'cv_upload' && type === 'file') {
        let cvInjected = false;
        if (targetProfile.cv_file) {
          cvInjected = injectCVFile(el, targetProfile.cv_file);
        }
        // Always attach helper badge next to file input
        attachCVHelperBadge(el, targetProfile.cv_path, cvInjected);
        if (cvInjected) {
          highlightElement(el);
          filledCount++;
          filledFields.push('cv_file');
        }
      } else if (type === 'radio') {
        if (valueToFill && setRadioValue(el, valueToFill)) {
          highlightElement(el.parentElement || el);
          filledCount++;
          filledFields.push(fieldKey);
        }
      } else if (el.tagName.toLowerCase() === 'select') {
        if (valueToFill && setSelectValue(el, valueToFill)) {
          highlightElement(el);
          filledCount++;
          filledFields.push(fieldKey);
        }
      } else if (valueToFill) {
        setNativeValue(el, valueToFill);
        highlightElement(el);
        filledCount++;
        filledFields.push(fieldKey);
      }
    });

    if (filledCount > 0) {
      showFloatingToast(`¡${filledCount} campo(s) rellenado(s) con éxito!`, '🚀');
    } else {
      showFloatingToast('No se detectaron campos de empleo en esta página', 'ℹ️');
    }

    return {
      success: true,
      filledCount,
      filledFields
    };
  }

  // Helper Badge for CV inputs (provides 1-click path copy or status)
  function attachCVHelperBadge(fileInput, cvPath, injected) {
    if (fileInput.dataset.jobautofillBadge) return;
    fileInput.dataset.jobautofillBadge = 'true';

    const wrapper = document.createElement('div');
    wrapper.className = 'jobautofill-cv-badge';

    let html = '';
    if (injected) {
      html += `<span class="badge-success">✅ CV Adjuntado</span>`;
    }
    if (cvPath) {
      html += `<button type="button" class="badge-btn-copy" title="Copiar ruta de archivo local al portapapeles">📋 Copiar ruta local</button>`;
    }

    if (!html) return;

    wrapper.innerHTML = html;
    fileInput.parentNode.insertBefore(wrapper, fileInput.nextSibling);

    const copyBtn = wrapper.querySelector('.badge-btn-copy');
    if (copyBtn) {
      copyBtn.addEventListener('click', (e) => {
        e.preventDefault();
        e.stopPropagation();
        navigator.clipboard.writeText(cvPath).then(() => {
          copyBtn.textContent = '¡Ruta copiada! 📋';
          setTimeout(() => { copyBtn.textContent = '📋 Copiar ruta local'; }, 2000);
        });
      });
    }
  }

  // Visual Highlight animation on filled inputs
  function highlightElement(el) {
    el.classList.add('jobautofill-highlight');
    setTimeout(() => {
      el.classList.remove('jobautofill-highlight');
    }, 2800);
  }

  // Floating Toast in Page
  function showFloatingToast(message, icon = '⚡') {
    let toast = document.getElementById('jobautofill-floating-toast');
    if (!toast) {
      toast = document.createElement('div');
      toast.id = 'jobautofill-floating-toast';
      document.body.appendChild(toast);
    }

    toast.innerHTML = `<span class="toast-icon">${icon}</span> <span class="toast-text">${message}</span>`;
    toast.className = 'jobautofill-toast-show';

    setTimeout(() => {
      toast.className = '';
    }, 3800);
  }

  // Scan total fillable fields on current DOM
  function countFillableFields() {
    const elements = document.querySelectorAll('input, select, textarea');
    let count = 0;
    elements.forEach(el => {
      if (identifyField(el)) count++;
    });
    return count;
  }

  // Floating Action Button (Widget) on page
  function updateOrRenderFloatingWidget() {
    const potentialCount = countFillableFields();
    if (potentialCount === 0 && !document.getElementById('jobautofill-fab-container')) {
      return;
    }

    let container = document.getElementById('jobautofill-fab-container');
    if (!container) {
      container = document.createElement('div');
      container.id = 'jobautofill-fab-container';
      container.innerHTML = `
        <div class="jobautofill-fab" id="jobautofill-fab" title="JobAutoFill: Rellenar formulario (Alt+Shift+F)">
          <div class="fab-icon">⚡</div>
          <div class="fab-label">
            <span>Rellenar Empleo</span>
            <span class="fab-badge" id="jobautofill-fab-badge">${potentialCount}</span>
          </div>
        </div>
      `;
      document.body.appendChild(container);

      const fab = document.getElementById('jobautofill-fab');
      fab.addEventListener('click', () => {
        if (typeof chrome !== 'undefined' && chrome.storage && chrome.storage.local) {
          chrome.storage.local.get(['job_autofill_profile'], (result) => {
            const profile = result?.job_autofill_profile;
            autofillJobForm(profile);
          });
        } else {
          // Standalone test fallback
          const localSaved = localStorage.getItem('job_autofill_profile');
          const profile = localSaved ? JSON.parse(localSaved) : STANDALONE_DEMO_PROFILE;
          autofillJobForm(profile);
        }
      });
    } else {
      const badge = document.getElementById('jobautofill-fab-badge');
      if (badge) {
        badge.textContent = potentialCount;
        badge.style.display = potentialCount > 0 ? 'inline-block' : 'none';
      }
    }
  }

  // Single Page Applications (SPA) / Multi-step Forms Observer
  let mutationDebounceTimer = null;
  function observeDynamicForms() {
    const observer = new MutationObserver((mutations) => {
      let hasFormChanges = false;
      for (const m of mutations) {
        if (m.addedNodes.length > 0 || m.removedNodes.length > 0) {
          hasFormChanges = true;
          break;
        }
      }
      if (hasFormChanges) {
        if (mutationDebounceTimer) clearTimeout(mutationDebounceTimer);
        mutationDebounceTimer = setTimeout(() => {
          updateOrRenderFloatingWidget();
        }, 400);
      }
    });

    observer.observe(document.body, {
      childList: true,
      subtree: true
    });
  }

  // Message Listener (from Popup, Background, or Keyboard Shortcut)
  if (typeof chrome !== 'undefined' && chrome.runtime && chrome.runtime.onMessage) {
    chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
      if (request.action === 'AUTOFILL') {
        if (request.profile) {
          const result = autofillJobForm(request.profile);
          sendResponse(result);
        } else {
          chrome.storage.local.get(['job_autofill_profile'], (res) => {
            const result = autofillJobForm(res?.job_autofill_profile);
            sendResponse(result);
          });
        }
        return true; // Keep channel open for async response
      }
    });
  }

  // Initialize
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
      updateOrRenderFloatingWidget();
      observeDynamicForms();
    });
  } else {
    updateOrRenderFloatingWidget();
    observeDynamicForms();
  }
})();
