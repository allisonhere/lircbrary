FROM node:20-alpine

WORKDIR /app

# Copy whichever lockfile exists; this COPY will fail if the file is missing,
# so we copy only package.json first, then fallback to npm install without lock.
COPY package.json ./
RUN npm install

COPY . .

EXPOSE 3000
CMD ["npm", "run", "dev", "--", "--host", "--port", "3000"]
