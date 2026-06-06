-- Criação da tabela de Usuários
CREATE TABLE usuarios (
    id SERIAL PRIMARY KEY,
    nome VARCHAR(100) NOT NULL,
    email VARCHAR(100) UNIQUE NOT NULL,
    senha_hash VARCHAR(255) NOT NULL
);

-- Criação da tabela de Questões para o Simulado
CREATE TABLE questoes (
    id SERIAL PRIMARY KEY,
    materia VARCHAR(50) NOT NULL,
    enunciado TEXT NOT NULL,
    alternativa_a TEXT NOT NULL,
    alternativa_b TEXT NOT NULL,
    alternativa_c TEXT NOT NULL,
    alternativa_d TEXT NOT NULL,
    alternativa_e TEXT NOT NULL,
    resposta_correta CHAR(1) NOT NULL
);

-- Histórico de Simulados feitos pelo aluno
CREATE TABLE simulados_historico (
    id SERIAL PRIMARY KEY,
    usuario_id INT REFERENCES usuarios(id),
    nota INT NOT NULL,
    data_envio TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Histórico de Redações enviadas e corrigidas por IA
CREATE TABLE redacoes (
    id SERIAL PRIMARY KEY,
    usuario_id INT REFERENCES usuarios(id),
    tema TEXT NOT NULL,
    texto TEXT NOT NULL,
    nota_final INT,
    feedback_ia TEXT,
    data_envio TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);