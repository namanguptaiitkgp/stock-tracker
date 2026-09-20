FROM node:20-alpine

WORKDIR /app

COPY package.json package-lock.json* ./
RUN npm ci || npm install

COPY . .

# Dev mode — Next picks up edits to the mounted ./frontend/src volume so
# changes show up immediately at :3000 without rebuilding the image.
# (For prod, build a separate image that runs `npm run build && npm start`.)
CMD ["npm", "run", "dev", "--", "--hostname", "0.0.0.0"]
