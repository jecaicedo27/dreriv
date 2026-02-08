#!/bin/bash
# Script de configuración de Skills para Bot Deriv V2
# Este script copia los skills custom a la ubicación correcta para Antigravity

set -e

PROJECT_DIR="/var/www/jhonk/dreriv"
SKILLS_SOURCE="${PROJECT_DIR}/skills/mnt/user-data/outputs/antigravity-skills"
SKILLS_TARGET="${PROJECT_DIR}/.agent/skills"

echo "🚀 Configurando Skills para Bot Deriv V2..."
echo ""

# Crear directorio .agent/skills si no existe
if [ ! -d "${SKILLS_TARGET}" ]; then
    echo "📁 Creando directorio ${SKILLS_TARGET}..."
    mkdir -p "${SKILLS_TARGET}"
else
    echo "✅ Directorio ${SKILLS_TARGET} ya existe"
fi

# Lista de skills custom a copiar
CUSTOM_SKILLS=(
    "deriv-websocket-trading"
    "groq-trading-decisions"
    "pgvector-pattern-matching"
    "statistical-trading-models"
    "trading-risk-management"
    "realtime-trading-dashboard"
)

echo ""
echo "📦 Copiando skills custom..."

# Copiar cada skill
for skill in "${CUSTOM_SKILLS[@]}"; do
    if [ -d "${SKILLS_SOURCE}/${skill}" ]; then
        echo "  ✅ Copiando ${skill}..."
        cp -r "${SKILLS_SOURCE}/${skill}" "${SKILLS_TARGET}/"
    else
        echo "  ⚠️  Advertencia: ${skill} no encontrado en ${SKILLS_SOURCE}"
    fi
done

# Copiar el skill raíz (deriv-websocket-trading está en /skills/SKILL.md)
if [ -f "${PROJECT_DIR}/skills/SKILL.md" ]; then
    echo "  ✅ Copiando skill raíz (deriv-websocket-trading)..."
    mkdir -p "${SKILLS_TARGET}/deriv-websocket-trading"
    cp "${PROJECT_DIR}/skills/SKILL.md" "${SKILLS_TARGET}/deriv-websocket-trading/"
fi

echo ""
echo "✨ ¡Skills configurados exitosamente!"
echo ""
echo "📋 Skills instalados:"
for skill in "${CUSTOM_SKILLS[@]}"; do
    if [ -d "${SKILLS_TARGET}/${skill}" ]; then
        echo "  ✓ ${skill}"
    fi
done

echo ""
echo "📖 Próximos pasos:"
echo "  1. Si usas Antigravity desktop, reinicia la sesión del agente"
echo "  2. Verifica los skills: pregunta '¿Qué skills tienes sobre Deriv o trading?'"
echo "  3. Revisa la guía de instalación completa: ${PROJECT_DIR}/skills/GUIA_INSTALACION.md"
echo ""
echo "🎯 Para comenzar el desarrollo, ve al documento:"
echo "  ${PROJECT_DIR}/NEXT_STEPS.md"
echo ""
