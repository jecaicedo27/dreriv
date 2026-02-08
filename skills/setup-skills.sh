#!/bin/bash
# =========================================
# SETUP SKILLS - Bot Deriv V2
# =========================================
# Este script instala todos los skills necesarios
# para el proyecto del bot de Deriv en Antigravity
#
# USO: 
#   chmod +x setup-skills.sh
#   ./setup-skills.sh
# =========================================

set -e

# Colores
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${BLUE}=========================================${NC}"
echo -e "${BLUE}  SETUP SKILLS - Bot Deriv V2${NC}"
echo -e "${BLUE}=========================================${NC}"
echo ""

# Detectar directorio del proyecto
PROJECT_DIR=$(pwd)
SKILLS_DIR="${PROJECT_DIR}/.agent/skills"

echo -e "${YELLOW}📁 Directorio del proyecto: ${PROJECT_DIR}${NC}"
echo -e "${YELLOW}📁 Skills se instalarán en: ${SKILLS_DIR}${NC}"
echo ""

# Crear directorio de skills si no existe
mkdir -p "$SKILLS_DIR"

# =========================================
# PASO 1: Skills de la Comunidad
# =========================================
echo -e "${GREEN}[1/3] Instalando skills de la comunidad...${NC}"

# Verificar si npx está disponible
if command -v npx &> /dev/null; then
    echo "  → Instalando con npx @rmyndharis/antigravity-skills..."
    
    COMMUNITY_SKILLS=(
        "fastapi-pro"
        "python-pro"
        "docker-expert"
        "async-python-patterns"
        "postgresql-schema-design"
        "api-security-best-practices"
        "nextjs-app-router-patterns"
        "senior-architect"
        "observability-engineer"
        "typescript-pro"
        "frontend-design"
        "auth-implementation-patterns"
    )
    
    for skill in "${COMMUNITY_SKILLS[@]}"; do
        echo "  → Instalando ${skill}..."
        npx @rmyndharis/antigravity-skills install "$skill" 2>/dev/null || echo "    ⚠️ ${skill} no encontrado, saltando..."
    done
else
    echo "  ⚠️ npx no disponible. Instalando desde git..."
    
    # Alternativa: clonar el repo completo
    TEMP_DIR=$(mktemp -d)
    git clone --depth 1 https://github.com/sickn33/antigravity-awesome-skills.git "$TEMP_DIR" 2>/dev/null
    
    COMMUNITY_SKILLS=(
        "fastapi-pro"
        "python-pro"
        "docker-expert"
        "async-python-patterns"
        "postgresql-schema-design"
        "api-security-best-practices"
        "nextjs-app-router-patterns"
        "senior-architect"
        "observability-engineer"
        "typescript-pro"
    )
    
    for skill in "${COMMUNITY_SKILLS[@]}"; do
        if [ -d "$TEMP_DIR/skills/$skill" ]; then
            cp -r "$TEMP_DIR/skills/$skill" "$SKILLS_DIR/"
            echo "  ✅ ${skill}"
        else
            echo "  ⚠️ ${skill} no encontrado"
        fi
    done
    
    rm -rf "$TEMP_DIR"
fi

echo ""

# =========================================
# PASO 2: Skills Custom (Deriv Bot)
# =========================================
echo -e "${GREEN}[2/3] Instalando skills custom del bot de Deriv...${NC}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

CUSTOM_SKILLS=(
    "deriv-websocket-trading"
    "groq-trading-decisions"
    "pgvector-pattern-matching"
    "statistical-trading-models"
    "trading-risk-management"
    "realtime-trading-dashboard"
)

for skill in "${CUSTOM_SKILLS[@]}"; do
    if [ -d "$SCRIPT_DIR/$skill" ]; then
        cp -r "$SCRIPT_DIR/$skill" "$SKILLS_DIR/"
        echo "  ✅ ${skill}"
    else
        echo "  ⚠️ ${skill} no encontrado en ${SCRIPT_DIR}"
    fi
done

echo ""

# =========================================
# PASO 3: Verificar
# =========================================
echo -e "${GREEN}[3/3] Verificando instalación...${NC}"
echo ""

TOTAL=$(find "$SKILLS_DIR" -name "SKILL.md" | wc -l)
echo -e "${BLUE}=========================================${NC}"
echo -e "${BLUE}  ✅ INSTALACIÓN COMPLETA${NC}"
echo -e "${BLUE}  📊 Total skills instalados: ${TOTAL}${NC}"
echo -e "${BLUE}=========================================${NC}"
echo ""
echo "Skills instalados:"
for skill_dir in "$SKILLS_DIR"/*/; do
    if [ -f "${skill_dir}SKILL.md" ]; then
        skill_name=$(basename "$skill_dir")
        echo "  • ${skill_name}"
    fi
done

echo ""
echo -e "${YELLOW}⚠️  IMPORTANTE: Reinicia la sesión del agente en Antigravity${NC}"
echo -e "${YELLOW}   para que detecte los nuevos skills.${NC}"
echo ""
echo -e "${GREEN}¡Listo! Ahora puedes empezar a desarrollar el bot.${NC}"
