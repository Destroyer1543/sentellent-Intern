FROM node:20-alpine

WORKDIR /app

# Install deps first (better caching)
COPY package*.json ./
RUN npm ci || npm install

# Copy source
COPY . .

EXPOSE 3000

CMD ["npm", "run", "dev", "--", "-p", "3000", "-H", "0.0.0.0"]
